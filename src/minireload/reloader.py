import os
import sys
import time
import inspect
import datetime
import threading
import traceback

from contextlib import contextmanager

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from minireload.autoreload import superreload


class ReloadEventHandler(FileSystemEventHandler):

    def __init__(self):

        self.lock = threading.Lock()
        self.reload_set = set()

    def pop_reload_set(self):

        with self.lock:
            rl = self.reload_set
            self.reload_set = set()

        return rl

    def on_any_event(self, event):

        if event.is_directory:
            return

        if event.event_type not in ["modified", "moved", "created", "deleted"]:
            return

        with self.lock:
            if event.src_path not in self.reload_set:
                self.reload_set.add(event.src_path)


class ReloadErrorInfo(Exception):

    def __init__(self, exc):

        self.exc = exc
        self.exc_str = traceback.format_exc()
        self.exc_time = datetime.datetime.now()
        (self.exc_type, self.exc_value, self.exc_tb) = sys.exc_info()

        if isinstance(exc, SyntaxError):
            self.exc_frames = []
        else:
            self.exc_frames = inspect.getinnerframes(self.exc_tb)


class Reloader:

    def __init__(self, reload_paths: list[tuple[str, bool]]):

        self.event_handler = ReloadEventHandler()

        self.observers = []
        for path, recursive in reload_paths:
            if not os.path.isabs(path):
                raise ValueError(f'reload path "{path}" must be an absolute path')
            observer = Observer()
            observer.schedule(self.event_handler, path, recursive)
            observer.start()

        self.reloaded_modules = []

        # needed for superreload
        self.old_objects = {}

    def reload(self):
        """
        Reloads all modified modules under the specified reload_paths.

        Returns True if at least one module was reloaded and False otherwise.
        """

        reload_set = self.event_handler.pop_reload_set()

        if len(reload_set) == 0:
            return False

        self.reloaded_modules = []

        for name, m in sys.modules.items():
            try:
                origin = m.__spec__.origin
            except AttributeError:
                continue

            # defer the reload because it may modify sys.modules
            if origin in reload_set:
                self.reloaded_modules.append(m)

        for m in self.reloaded_modules:
            superreload(m, old_objects=self.old_objects)

        return True


class WrappingReloader(Reloader):

    def __init__(self,
                 func,
                 reload_paths: list[tuple[str, bool]],
                 retry_after_secs=0.1):

        super().__init__(reload_paths)

        self.func = func
        self.retry_after_secs = retry_after_secs

        self.exc_info = None

    def __call__(self, *args, **kwargs):

        try:
            if self.reload():
                self.exc_info = None

            if self.exc_info is None:
                return self.func(*args, **kwargs)
            else:
                time.sleep(self.retry_after_secs)
                return self.exc_info
        except KeyboardInterrupt as e:
            raise e
        except SystemExit as e:
            raise e
        except Exception as e:
            traceback.print_exc()
            self.exc_info = ReloadErrorInfo(e)
            return self.exc_info
