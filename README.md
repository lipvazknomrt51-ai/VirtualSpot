# VirtualSpot

Simulate your iPhone’s GPS location from Windows.

Plan routes, teleport to any location, and move freely with your keyboard or joystick.

## Features

- 📍 Teleport to any location by map, coordinates, or search.
- 🗺️ Multi-point routes with walking, driving, cycling, or straight-line modes.
- ▶️ Route playback with loop, ping-pong, speed control, and progress tracking.
- 🎮 Move with WASD, arrow keys, or an on-screen joystick.
- 📦 Import/export GPX and save/load routes.
- ⭐ Favorites with groups, recent locations, and JSON backup.
- 🌐 Standard, satellite, and terrain maps.
- 🌙 Light, dark, and system themes.
- 🌏 English and Traditional Chinese interfaces.
- 📱 Shows connected iPhone and iOS information.
- 💻 Works without an iPhone for route planning and GPX export.

## Installation

Download the latest release:

- `VirtualSpot-Setup-x.y.z.exe` — Windows installer
- `VirtualSpot-Portable-x.y.z.zip` — Portable version

The application is unsigned. If Windows SmartScreen appears, select **More info → Run anyway**.

## iPhone Setup

1. Install **Apple Devices** or **iTunes** from Microsoft.
2. Connect your iPhone via USB and tap **Trust**.
3. Enable **Developer Mode** under **Settings → Privacy & Security**.
4. Start VirtualSpot.
5. Select a location and click **Start**.

VirtualSpot does not change your location until you start a simulation. Click **Stop** to restore your real location.

iOS 17+ requires Developer Mode and a tunnel service. VirtualSpot starts the required service automatically.

## Run from Source

```
pip install -r requirements.txt
python app.py
```

Run as Administrator when required for iOS 17+.

## Tests

```
python tests/run_all.py
```

Tests run without an iPhone, display, or network connection.

## Troubleshooting

If the iPhone cannot connect:

- Make sure Apple Devices/iTunes is installed.
- Make sure the iPhone is unlocked and trusted.
- Make sure Developer Mode is enabled.
- Close other GPS/location tools.
- Use **Settings → Save Diagnostic Report** for troubleshooting.

## License

MIT License. See [LICENSE](LICENSE).

## Disclaimer

VirtualSpot is intended for development, testing, and privacy-related use.

Using simulated locations in third-party applications may violate their terms of service and could result in account restrictions. Use responsibly.
