import time

import minireload as mr


def update():

    print("Try changing me!")
    time.sleep(0.1)

    return 42


def main():

    enable_autoreload = True

    if enable_autoreload:
        func = mr.WrappingReloader(update)
    else:
        func = update

    while True:
        res = func()

        if type(res) == mr.ReloadErrorInfo:
            print("Everything is awful:", res)
        else:
            print("Everything is awesome:", res)
