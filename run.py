import argparse
import socket
import threading
import webbrowser

from app import create_app


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def is_port_available(port: int) -> bool:
    for host, family in (("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.25)
                if probe.connect_ex((host, port)) == 0:
                    return False
        except OSError:
            pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(("0.0.0.0", port))
            return True
    except OSError:
        return False


def find_available_port(preferred_port: int, max_tries: int = 50) -> int:
    for offset in range(max_tries):
        candidate = preferred_port + offset
        if is_port_available(candidate):
            return candidate
    return preferred_port


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Motorbike Rentals Camiguin PWA Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5050, help="Preferred port number (default: 5050)")
    parser.add_argument("--open", action="store_true", help="Open the browser automatically once started")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    port = find_available_port(args.port)
    app = create_app()
    lan_ip = get_lan_ip()
    local_url = f"http://127.0.0.1:{port}"

    print("=" * 60)
    print("  Motorbike Rentals Camiguin — Website + PWA")
    print("=" * 60)
    if port != args.port:
        print(f"  Note: Port {args.port} was busy, using free port {port}.")
    print(f"  PC Browser:     {local_url}")
    print(f"  Phone (Wi-Fi):  http://{lan_ip}:{port}")
    print(f"  Admin Portal:   {local_url}/admin")
    print("=" * 60)
    print("  Press Ctrl+C to stop the server.")

    if args.open:
        threading.Timer(1.0, webbrowser.open, args=[local_url]).start()

    app.run(host=args.host, port=port, debug=args.debug)


if __name__ == "__main__":
    main()
