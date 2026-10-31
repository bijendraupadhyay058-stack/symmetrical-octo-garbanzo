"""Desktop entry point. If the program cannot start (for example a library that does not load on this PC),
it shows a plain message and writes a report the user can send for support, instead of a raw traceback."""
import os
import sys


def _report(exc: BaseException) -> str:
    import datetime
    import platform
    import traceback

    lines = [f"FIN TAX PRO could not start – {datetime.datetime.now():%d-%m-%Y %H:%M}",
             f"Windows: {platform.platform()}  ({platform.machine()})",
             f"Python: {sys.version.split()[0]}"]
    if os.name == "nt":
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            lines.append(f"Processor: {winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()}")
        except OSError:
            lines.append(f"Processor: {platform.processor()}")
        try:
            import ctypes

            present = ctypes.windll.kernel32.IsProcessorFeaturePresent
            features = {"SSE3": 13, "SSSE3": 36, "SSE4.1": 37, "SSE4.2": 38, "AVX": 39, "AVX2": 40}
            lines.append("CPU features: " + ", ".join(f"{n} {'yes' if present(v) else 'NO'}"
                                                      for n, v in features.items()))
        except (OSError, AttributeError):
            pass
    lines += ["", "".join(traceback.format_exception(exc))]
    return "\n".join(lines)


def _fail(exc: BaseException) -> int:
    text = _report(exc)
    folder = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "FinTaxPro")
    path = os.path.join(folder, "startup-error.txt")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        path = "(could not be saved)"
    message = ("FIN TAX PRO could not start on this computer.\n\n"
               f"A report was saved to:\n{path}\n\n"
               "Please send that file to your FIN TAX PRO support contact. Your data is not affected.\n\n"
               f"Error: {str(exc)[:300]}")
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "FIN TAX PRO", 0x10)
            return 1
        except (OSError, AttributeError):
            pass
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        from fintax_gst.ui.app import main

        code = main()
    except Exception as exc:  # noqa: BLE001 - any failure to start the program is reported to the user
        code = _fail(exc)
    raise SystemExit(code)
