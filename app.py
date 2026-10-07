"""VirtualSpot 啟動器。

新介面（customtkinter）載入失敗或缺少套件時，會自動改用舊介面，並在狀態列說明原因。
強制使用舊介面：python app.py --classic
"""
import sys

if "--tunneld" in sys.argv:      # 子程序模式：只跑 tunneld，不開視窗
    from tunnel import run_tunneld_cli

    run_tunneld_cli()
    sys.exit(0)

import os
import traceback

if "--selftest" in sys.argv:     # 打包後冒煙測試：確認關鍵模組都有被收進 exe
    _out = sys.argv[sys.argv.index("--selftest") + 1] if len(sys.argv) > sys.argv.index("--selftest") + 1 else None
    _msg, _code = "OK", 0
    try:
        import customtkinter, tkintermapview, pymobiledevice3  # noqa: F401,E401
        import core, device, tunnel, ui_modern  # noqa: F401,E401
        from version import __version__
        _msg = f"OK {__version__}"
    except Exception:  # noqa: BLE001
        _msg, _code = "FAIL\n" + traceback.format_exc(), 1
    if _out:
        with open(_out, "w", encoding="utf-8") as _f:
            _f.write(_msg)
    sys.exit(_code)


def _log_error(text):
    try:
        from storage import DIR

        os.makedirs(DIR, exist_ok=True)
        with open(os.path.join(DIR, "ui_error.log"), "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:  # noqa: BLE001
        pass


def main():
    reason = None
    if "--classic" not in sys.argv:
        try:
            import customtkinter as ctk

            from ui_modern import ModernApp

            from storage import load_settings

            _theme = load_settings().get("theme", "dark")
            ctk.set_appearance_mode(_theme if _theme in ("light", "dark", "system") else "dark")
            ctk.set_default_color_theme("blue")
            root = ctk.CTk()
            try:
                ModernApp(root)
            except Exception as e:  # noqa: BLE001
                reason = f"{type(e).__name__}: {e}"
                _log_error(traceback.format_exc())
                try:
                    root.destroy()
                except Exception:  # noqa: BLE001
                    pass
            else:
                root.mainloop()
                return
        except Exception as e:  # noqa: BLE001  例如沒裝 customtkinter
            reason = f"{type(e).__name__}: {e}"
            _log_error(traceback.format_exc())

    import tkinter as tk

    from core import App

    root = tk.Tk()
    app = App(root)
    if reason:
        app.status.set(f"新介面載入失敗，已改用舊介面（{reason}）")
    root.mainloop()


if __name__ == "__main__":
    main()
