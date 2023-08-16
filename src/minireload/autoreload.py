"""
A module for automatic code reloading.

Caveats
=======
Reloading Python modules in a reliable way is in general difficult,
and unexpected things may occur. autoreload tries to work around
common pitfalls by replacing function code objects and parts of
classes previously in the module with new versions. This makes the
following things to work:
- Functions and classes imported via 'from xxx import foo' are upgraded
  to new versions when 'xxx' is reloaded.
- Methods and properties of classes are upgraded on reload, so that
  calling 'c.foo()' on an object 'c' created before the reload causes
  the new code for 'foo' to be executed.
Some of the known remaining caveats are:
- Replacing code objects does not always succeed: changing a @property
  in a class to an ordinary method or a method to a member variable
  can cause problems (but in old objects only).
- Functions that are removed (eg. via monkey-patching) from a module
  before it is reloaded are not upgraded.
- C extension modules cannot be reloaded, and so cannot be autoreloaded.
"""

# Copyright (C) 2000 Thomas Heller
# Copyright (C) 2008 Pauli Virtanen <pav@iki.fi>
# Copyright (C) 2012 The IPython Development Team
#
# The original IPython module was written by Pauli Virtanen, based on the
# autoreload code by Thomas Heller and distributed under BSD 3-Clause.
#
# BSD 3-Clause License
#
# - Copyright (c) 2008-Present, IPython Development Team
# - Copyright (c) 2001-2007, Fernando Perez <fernando.perez@colorado.edu>
# - Copyright (c) 2001, Janko Hauser <jhauser@zscout.de>
# - Copyright (c) 2001, Nathaniel Gray <n8gray@caltech.edu>
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# This module was adapted for the minireload library (2023-03-26).

import os
import gc
import sys
import types
import queue
import signal
import weakref

from importlib import reload

import multiprocessing as mp

# ------------------------------------------------------------------------------
# Autoreload functionality
# ------------------------------------------------------------------------------


def scan_modules(requests, results):

    while True:
        try:
            try:
                mtime_table, req = requests.get(timeout=2.0)
            except queue.Empty:
                return

            needs_reload = []

            for name, origin in req.items():

                if name in [None, "__mp_main__", "__main__"]:
                    # we cannot reload(__main__) or reload(__mp_main__)
                    continue

                if origin in [None, "built-in", "frozen"]:
                    # builtins or frozen modules will likely not change
                    continue

                try:
                    mtime = os.stat(origin).st_mtime
                except OSError:
                    continue

                try:
                    if mtime_table[name] < mtime:
                        needs_reload.append(name)
                        mtime_table[name] = mtime
                except KeyError:
                    mtime_table[name] = mtime

            results.put((mtime_table, needs_reload))
        except KeyboardInterrupt:
            return


class ModuleReloader:

    def __init__(self):

        self.waiting_for_scan = False

        self.init_subproc()

        # (module-name, name) -> weakref, for replacing old code objects
        self.old_objects = {}

        self.mtime_table = {}

    def init_subproc(self):

        self.waiting_for_scan = False

        self.scan_requests = mp.Queue(1)
        self.scan_results = mp.Queue(1)

        self.scan_process = mp.Process(
                daemon=True,
                target=scan_modules,
                args=[self.scan_requests, self.scan_results])

        self.scan_process.start()

    def cleanup(self):

        if self.scan_process is not None:
            # no patience, no mercy
            os.kill(self.scan_process.pid, signal.SIGKILL)
            self.scan_process = None

    def reload(self):
        """
        Check whether some modules need to be reloaded.
        """

        # check if the module scan was completed

        try:
            self.mtime_table, changed = self.scan_results.get_nowait()
            self.waiting_for_scan = False
        except queue.Empty:
            changed = []

        # check if the process is still alive

        if not self.scan_process.is_alive():
            self.init_subproc()

        if not self.waiting_for_scan:

            # submit currently imported modules to scan process

            modules_to_scan = {}

            for name, mt in sys.modules.items():
                try:
                    modules_to_scan[name] = mt.__spec__.origin
                except AttributeError:
                    continue

            self.scan_requests.put((self.mtime_table, modules_to_scan))
            self.waiting_for_scan = True

        # ok there are some modules we need to reload

        if changed == []:
            return False

        for modname in changed:
            m = sys.modules.get(modname, None)
            superreload(m, reload, self.old_objects)

        return True


# ------------------------------------------------------------------------------
# superreload
# ------------------------------------------------------------------------------


func_attrs = [
    "__code__",
    "__defaults__",
    "__doc__",
    "__closure__",
    "__globals__",
    "__dict__",
]


def update_function(old, new):
    """Upgrade the code object of a function"""
    for name in func_attrs:
        try:
            setattr(old, name, getattr(new, name))
        except (AttributeError, TypeError):
            pass


def update_instances(old, new):
    """Use garbage collector to find all instances that refer to the old
    class definition and update their __class__ to point to the new class
    definition"""

    refs = gc.get_referrers(old)

    for ref in refs:
        if type(ref) is old:
            ref.__class__ = new


def update_class(old, new):
    """Replace stuff in the __dict__ of a class, and upgrade
    method code objects, and add new methods, if any"""
    for key in list(old.__dict__.keys()):
        old_obj = getattr(old, key)
        try:
            new_obj = getattr(new, key)
            # explicitly checking that comparison returns True to handle
            # cases where `==` doesn't return a boolean.
            if (old_obj == new_obj) is True:
                continue
        except AttributeError:
            # obsolete attribute: remove it
            try:
                delattr(old, key)
            except (AttributeError, TypeError):
                pass
            continue

        if update_generic(old_obj, new_obj):
            continue

        try:
            setattr(old, key, getattr(new, key))
        except (AttributeError, TypeError):
            pass  # skip non-writable attributes

    for key in list(new.__dict__.keys()):
        if key not in list(old.__dict__.keys()):
            try:
                setattr(old, key, getattr(new, key))
            except (AttributeError, TypeError):
                pass  # skip non-writable attributes

    # update all instances of class
    update_instances(old, new)


def update_property(old, new):
    """Replace get/set/del functions of a property"""
    update_generic(old.fdel, new.fdel)
    update_generic(old.fget, new.fget)
    update_generic(old.fset, new.fset)


def isinstance2(a, b, typ):
    return isinstance(a, typ) and isinstance(b, typ)


UPDATE_RULES = [
    (lambda a, b: isinstance2(a, b, type), update_class),
    (lambda a, b: isinstance2(a, b, types.FunctionType), update_function),
    (lambda a, b: isinstance2(a, b, property), update_property),
]
UPDATE_RULES.extend(
    [
        (
            lambda a, b: isinstance2(a, b, types.MethodType),
            lambda a, b: update_function(a.__func__, b.__func__),
        ),
    ]
)


def update_generic(a, b):
    for type_check, update in UPDATE_RULES:
        if type_check(a, b):
            update(a, b)
            return True
    return False


class StrongRef:
    def __init__(self, obj):
        self.obj = obj

    def __call__(self):
        return self.obj


mod_attrs = [
    "__name__",
    "__doc__",
    "__package__",
    "__loader__",
    "__spec__",
    "__file__",
    "__cached__",
    "__builtins__",
]


def append_obj(module, d, name, obj, autoload=False):
    in_module = hasattr(obj, "__module__") and obj.__module__ == module.__name__
    if autoload:
        # check needed for module global built-ins
        if not in_module and name in mod_attrs:
            return False
    else:
        if not in_module:
            return False

    key = (module.__name__, name)
    try:
        d.setdefault(key, []).append(weakref.ref(obj))
    except TypeError:
        pass
    return True


def superreload(module, reload=reload, old_objects=None, shell=None):
    """Enhanced version of the builtin reload function.
    superreload remembers objects previously in the module, and
    - upgrades the class dictionary of every old class in the module
    - upgrades the code object of every old function and method
    - clears the module's namespace before reloading
    """
    if old_objects is None:
        old_objects = {}

    # collect old objects in the module
    for name, obj in list(module.__dict__.items()):
        if not append_obj(module, old_objects, name, obj):
            continue
        key = (module.__name__, name)
        try:
            old_objects.setdefault(key, []).append(weakref.ref(obj))
        except TypeError:
            pass

    # reload module
    try:
        # In contrast to the original superreload version
        # we do not clear the namespace, as this produces
        # (additional) problems when using multiple threads.
        old_dict = module.__dict__.copy()
    except (TypeError, AttributeError, KeyError):
        pass

    try:
        module = reload(module)
    except:
        # restore module dictionary on failed reload
        module.__dict__.update(old_dict)
        raise

    # iterate over all objects and update functions & classes
    for name, new_obj in list(module.__dict__.items()):
        key = (module.__name__, name)
        if key not in old_objects:
            # here 'shell' acts both as a flag and as an output var
            if (
                shell is None
                or name == "Enum"
                or not append_obj(module, old_objects, name, new_obj, True)
            ):
                continue
            shell.user_ns[name] = new_obj

        new_refs = []
        for old_ref in old_objects[key]:
            old_obj = old_ref()
            if old_obj is None:
                continue
            new_refs.append(old_ref)
            update_generic(old_obj, new_obj)

        if new_refs:
            old_objects[key] = new_refs
        else:
            del old_objects[key]

    return module
