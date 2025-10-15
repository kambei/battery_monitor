#!/usr/bin/env python3

import gi
gi.require_version('Gtk', '3.0')
try:
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3 as appindicator
    APPINDICATOR_AVAILABLE = True
except (ValueError, ImportError):
    APPINDICATOR_AVAILABLE = False
    print("Warning: AppIndicator3 not found. Tray icon functionality will be limited or unavailable.")
    print("Try: sudo dnf install libappindicator-gtk3")

from gi.repository import Gtk, GLib, GdkPixbuf

import dbus
import subprocess
import os

# --- Configuration ---
LOW_BATTERY_THRESHOLD = 30  # Percentage
CHECK_INTERVAL_SECONDS = 60  # Interval for checking battery status in seconds
APP_ID = "dev.kambei.batterymonitorgui" # Unique ID for AppIndicator
NOTIFICATION_APP_NAME = "BatteryMonitorGUI"
NOTIFICATION_ICON = "battery-caution"
LOW_BATTERY_SOUND_FILE = "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga"

# Icon names for AppIndicator
TRAY_ICON_NAME_FULL = "battery-full"
TRAY_ICON_NAME_GOOD = "battery-good"
TRAY_ICON_NAME_MEDIUM = "battery-caution"
TRAY_ICON_NAME_LOW = "battery-low"
TRAY_ICON_NAME_EMPTY = "battery-empty"
TRAY_ICON_NAME_CHARGING = "battery-good-charging"
TRAY_ICON_NAME_CHARGING_FULL = "battery-full-charging"
TRAY_ICON_NAME_ERROR = "dialog-error"  # For when battery info fails
TRAY_ICON_NAME_DEFAULT = "battery"  # Fallback


class BatteryMonitorWindow(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Battery Monitor")
        self.set_border_width(15)
        self.set_default_size(320, 150) # Slightly more height for clarity
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_deletable(False) # Prevent closing from window manager X button directly
        self.connect("delete-event", self.on_window_close_request)

        self.low_battery_notified = False
        self.indicator = None # Will hold the AppIndicator3 instance

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        self.status_label = Gtk.Label(label="Initializing battery status...")
        self.status_label.set_xalign(0)
        vbox.pack_start(self.status_label, True, True, 0)

        self.level_bar = Gtk.LevelBar()
        self.level_bar.set_min_value(0)
        self.level_bar.set_max_value(100)
        vbox.pack_start(self.level_bar, True, True, 0)

        if APPINDICATOR_AVAILABLE:
            self.setup_app_indicator()
        else:
            print("AppIndicator not available, tray icon will not be created.")
            # Fallback: if no appindicator, allow normal window close
            self.set_deletable(True)
            if self.is_connected_by_func(self.on_window_close_request): # Check if connected before disconnecting
                self.disconnect_by_func(self.on_window_close_request) # remove custom close
            self.connect("destroy", Gtk.main_quit) # quit on close if no tray

        self.update_battery_display() # Initial update
        GLib.timeout_add_seconds(CHECK_INTERVAL_SECONDS, self.update_battery_display)

        if not os.path.exists(LOW_BATTERY_SOUND_FILE):
            print(f"Warning: Sound file '{LOW_BATTERY_SOUND_FILE}' not found. Low battery sound may not play.")

    def is_connected_by_func(self, func):
        # Helper to check if a signal is connected by a specific function
        # This is a bit more involved to do robustly without knowing the exact signal id
        # For simplicity, we assume if on_window_close_request might be connected,
        # it's okay to try disconnecting if APPINDICATOR_AVAILABLE is false.
        # A more robust way would be to store signal IDs.
        # However, Gtk.Widget.disconnect_by_func should not error if not connected.
        return True # Assume it might be for safety, disconnect_by_func handles if not.


    def on_window_close_request(self, widget, event):
        """Handles the window's close button (X). Hides the window instead of quitting."""
        self.hide()
        return True # Prevents the default handler from destroying the window

    def setup_app_indicator(self):
        """Sets up the AppIndicator3 system tray icon and its menu."""
        self.indicator = appindicator.Indicator.new(
            APP_ID,
            TRAY_ICON_NAME_DEFAULT, # Initial icon
            appindicator.IndicatorCategory.HARDWARE)
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE)

        menu = Gtk.Menu()

        item_toggle_window = Gtk.MenuItem(label="Show/Hide Window")
        item_toggle_window.connect("activate", self.on_toggle_window_visibility)
        menu.append(item_toggle_window)

        item_quit = Gtk.MenuItem(label="Quit Battery Monitor")
        item_quit.connect("activate", self.on_quit_application)
        menu.append(item_quit)

        menu.show_all()
        self.indicator.set_menu(menu)

        self.indicator.set_title("Battery Monitor")


    def on_toggle_window_visibility(self, widget):
        """Toggles the main window's visibility."""
        if self.is_visible():
            self.hide()
        else:
            self.present() # Brings window to front and shows it

    def on_quit_application(self, widget=None):
        """Quits the GTK application."""
        print("Battery Monitor GUI quitting...")
        Gtk.main_quit()

    def get_battery_info_sync(self):
        try:
            bus = dbus.SystemBus()
            upower_proxy = bus.get_object('org.freedesktop.UPower', '/org/freedesktop/UPower')
            upower_interface = dbus.Interface(upower_proxy, 'org.freedesktop.UPower')
            devices = upower_interface.EnumerateDevices()
            for dev_path in devices:
                if 'battery' in dev_path.lower():
                    dev_proxy = bus.get_object('org.freedesktop.UPower', dev_path)
                    props_interface = dbus.Interface(dev_proxy, dbus.PROPERTIES_IFACE)
                    device_type = props_interface.Get('org.freedesktop.UPower.Device', 'Type')
                    if device_type == 2:
                        percentage = props_interface.Get('org.freedesktop.UPower.Device', 'Percentage')
                        state = props_interface.Get('org.freedesktop.UPower.Device', 'State')
                        is_discharging = (state == 2 or state == 6)
                        is_charging = (state == 1 or state == 5)
                        return float(percentage), bool(is_discharging), bool(is_charging)
            print("GUI: No battery device found.")
            return None, False, False
        except dbus.exceptions.DBusException as e:
            print(f"GUI: Error connecting to D-Bus or UPower: {e}")
            if hasattr(self, 'status_label'): self.status_label.set_text("Error: D-Bus/UPower connection failed.")
            return None, False, False
        except Exception as e:
            print(f"GUI: An unexpected error occurred while getting battery info: {e}")
            if hasattr(self, 'status_label'): self.status_label.set_text("Error: Failed to retrieve battery data.")
            return None, False, False

    def send_notification_sync(self, summary, body, icon_name):
        try:
            bus = dbus.SessionBus()
            notifications_proxy = bus.get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
            notifications_interface = dbus.Interface(notifications_proxy, 'org.freedesktop.Notifications')
            notifications_interface.Notify(NOTIFICATION_APP_NAME, 0, icon_name, summary, body, [], {}, 5000)
            print(f"GUI: Notification sent: {summary}")
        except Exception as e:
            print(f"GUI: Error sending notification: {e}")

    def play_sound_sync(self, sound_file_path):
        if not os.path.exists(sound_file_path):
            print(f"GUI: Sound file not found: {sound_file_path}")
            return
        try:
            subprocess.run(['paplay', sound_file_path], check=True, capture_output=True)
            print(f"GUI: Played sound: {sound_file_path}")
        except Exception as e:
            print(f"GUI: Error playing sound: {e}")

    def update_battery_display(self):
        percentage, is_discharging, is_charging = self.get_battery_info_sync()

        icon_to_set = TRAY_ICON_NAME_DEFAULT
        tooltip_parts = ["Battery Monitor"]

        if percentage is None:
            self.status_label.set_markup("<b>Battery:</b> Error retrieving data")
            self.level_bar.set_value(0)
            icon_to_set = TRAY_ICON_NAME_ERROR
            tooltip_parts = ["Battery: Error"]
        else:
            current_status_text = "Unknown"
            if is_discharging:
                current_status_text = "Discharging"
                self.level_bar.set_mode(Gtk.LevelBarMode.CONTINUOUS)
                if percentage > 95:
                    icon_to_set = TRAY_ICON_NAME_FULL
                elif percentage > 70:
                    icon_to_set = TRAY_ICON_NAME_GOOD
                elif percentage > LOW_BATTERY_THRESHOLD:
                    icon_to_set = TRAY_ICON_NAME_MEDIUM
                elif percentage > 10:
                    icon_to_set = TRAY_ICON_NAME_LOW
                else:
                    icon_to_set = TRAY_ICON_NAME_EMPTY
            elif is_charging:
                current_status_text = "Charging"
                if percentage > 98:
                    icon_to_set = TRAY_ICON_NAME_CHARGING_FULL
                else:
                    icon_to_set = TRAY_ICON_NAME_CHARGING
            else:  # Not discharging, not charging -> likely Full or other
                if percentage > 98:
                    current_status_text = "Full"
                    icon_to_set = TRAY_ICON_NAME_FULL
                else:
                    current_status_text = "Plugged In"
                    if percentage > 95:
                        icon_to_set = TRAY_ICON_NAME_FULL
                    elif percentage > 70:
                        icon_to_set = TRAY_ICON_NAME_GOOD
                    elif percentage > LOW_BATTERY_THRESHOLD:
                        icon_to_set = TRAY_ICON_NAME_MEDIUM
                    else:
                        icon_to_set = TRAY_ICON_NAME_LOW

            self.status_label.set_markup(f"<b>Battery:</b> {percentage:.0f}% <i>({current_status_text})</i>")
            self.level_bar.set_value(percentage)
            tooltip_parts = [f"Battery: {percentage:.0f}% ({current_status_text})"]

            if is_discharging and percentage <= LOW_BATTERY_THRESHOLD:
                if not self.low_battery_notified:
                    summary = "Low Battery Warning"
                    body = f"Your battery is at {percentage:.0f}%. Please connect to a power source."
                    print(f"GUI: LOW BATTERY DETECTED: {percentage:.0f}%")
                    self.send_notification_sync(summary, body, NOTIFICATION_ICON)
                    self.play_sound_sync(LOW_BATTERY_SOUND_FILE)
                    self.low_battery_notified = True
            elif percentage > LOW_BATTERY_THRESHOLD + 5:
                self.low_battery_notified = False

        if APPINDICATOR_AVAILABLE and self.indicator:
            self.indicator.set_icon_full(icon_to_set, ", ".join(tooltip_parts))

        return True


def main():
    print("Starting Battery Monitor GUI (using AppIndicator3 if available)...")
    print(f"Low battery threshold: {LOW_BATTERY_THRESHOLD}%")
    print(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")

    if not APPINDICATOR_AVAILABLE:
        print("--------------------------------------------------------------------")
        print("NOTE: AppIndicator3 library not found or failed to load.")
        print("The application will run without a tray icon.")
        print("To enable the tray icon, please install 'libappindicator-gtk3':")
        print("  sudo dnf install libappindicator-gtk3")
        print("You may also need a GNOME Shell extension for AppIndicators,")
        print("such as 'AppIndicator and KStatusNotifierItem Support'.")
        print("--------------------------------------------------------------------")

    win = BatteryMonitorWindow()
    # Make the window and all its children visible at startup.
    win.show_all()

    Gtk.main()

if __name__ == "__main__":
    main()
