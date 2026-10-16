// ==========================================================================
// Diagnostics
// ==========================================================================
// There is one build. The host window shows everything the board reports, so
// the status line, connection events and the key echo are always compiled in:
// they cost one short line every five seconds.

#if 1
// NimBLE host stack log level: 0=DEBUG 1=INFO 2=WARN 3=ERR 5=off.
// This must be defined before <NimBLEDevice.h> is included: nimconfig.h guards
// the symbol with #ifndef, so a later definition has no effect.
//
// CONFIG_BT_NIMBLE_LOG_LEVEL alone is not sufficient for the messages to appear.
// NimBLE logs through ESP_LOG, which removes low level messages at compile time
// according to LOG_LOCAL_LEVEL, while this board's prebuilt sdkconfig sets
// CONFIG_LOG_MAXIMUM_LEVEL=1 (ERROR only). Emitting stack logs therefore also
// requires -DLOG_LOCAL_LEVEL=5 on the compiler command line, plus the runtime
// level raised in startBle().
#define CONFIG_BT_NIMBLE_LOG_LEVEL 0
#endif

// ==========================================================================
// Required NimBLE patch: orphaned Service Changed characteristic
// ==========================================================================
// NimBLE's GATT service (0x1801) unconditionally registers Service Changed
// (0x2A05), while Database Hash (0x2B2A) sits behind MYNEWT_VAL(BLE_GATT_CACHING)
// (nimble/host/services/gatt/src/ble_svc_gatt.c), which this board leaves
// disabled. The attribute table therefore advertises "Service Changed supported"
// without the paired Database Hash; BLE 5.1 requires the two together and
// defines no behaviour for the mismatch.
//
// Enabling CONFIG_BT_NIMBLE_GATT_CACHING instead is not viable on NimBLE 2.5.1:
// ble_gatts.c declares `int i` twice and fails to compile, and a hand-patched
// build crashes and reboots at power-on.
//
// The characteristic is registered inside the library, so no sketch macro can
// remove it; this firmware therefore assumes a NimBLE-Arduino with Service
// Changed removed from ble_svc_gatt.c.
//
// Consequence: the device never announces that its attribute table changed, so a
// peer that cached an older table must be forgotten and re-paired after a
// firmware update.

// Must be defined before <esp_mac.h> is included. The preprocessor is
// single-pass, so the #if WINBORDER_CUSTOM_BLE_MAC that guards that include would
// evaluate to 0 if this appeared later, leaving esp_read_mac and
// esp_iface_mac_addr_set undeclared.
#define WINBORDER_CUSTOM_BLE_MAC 1

// Requires NimBLE-Arduino >= 2.0.0 (h2zero) on an ESP32 variant with native BLE:
// ESP32-C3 / C6 / S3, or a classic ESP32-WROOM-32.
#include <NimBLEDevice.h>
// NimBLEHIDDevice is declared in its own header; without it the compiler reports
// 'NimBLEHIDDevice' does not name a type.
#include <NimBLEHIDDevice.h>
#include <Arduino.h>
#if WINBORDER_CUSTOM_BLE_MAC
#include <esp_mac.h>       // esp_read_mac / esp_iface_mac_addr_set
#endif

// ==========================================================================
// Tunables
// ==========================================================================
// Changing the device name makes the target and Windows treat the board as a new
// device, which discards their cached GATT tables and forces a fresh service
// discovery. Pairing must be redone afterwards.
#define WINBORDER_DEVICE_NAME "Winborder"

// ==========================================================================
// BLE identity (MAC address)
// ==========================================================================
// GATT caches and "other devices" memory on iOS and Windows are keyed by BLE
// address, not by device name, so renaming does not invalidate them. On iOS a
// device that never completed pairing appears only under "Other Devices", which
// offers no "Forget This Device" action, so a stale cache cannot be cleared from
// the interface. Assigning an unused address presents the peer with a device it
// has never seen, which invalidates every address-keyed cache.
//
// The address is derived from the factory MAC (Espressif OUI preserved, last two
// bytes replaced), so it is stable per board and reproducible. Increment
// WINBORDER_MAC_SUFFIX_1 for a new identity. The address must also be changed after
// editing any device-class field such as GAP Appearance, because iOS caches the
// device class by address.
#define WINBORDER_MAC_SUFFIX_0 0x9C
#define WINBORDER_MAC_SUFFIX_1 0x7B      // increment for each new identity

// May be enabled while changing the address, to drop the device-side bonds.
// Must stay 0 otherwise: pairing state is stored on both sides, so clearing only
// the local half leaves the peer holding a key the device no longer has. The
// peer then starts encryption the device cannot answer, the connection is
// rejected, and the user has to forget the device before pairing again.
#define WINBORDER_WIPE_BONDS_ON_BOOT 0

// Must run before the BLE controller starts, otherwise the interface address is
// already fixed and the write has no effect.
static void applyCustomBleMac() {
#if WINBORDER_CUSTOM_BLE_MAC
  uint8_t mac[6] = {0};
  esp_err_t rc = esp_read_mac(mac, ESP_MAC_BT);
  if (rc != ESP_OK) {
    Serial.printf("[ble] !! failed to read factory MAC rc=%d, keeping factory address\n",
                  (int)rc);
    return;
  }
  uint8_t orig[6];
  memcpy(orig, mac, sizeof(orig));

  mac[5] = WINBORDER_MAC_SUFFIX_1;
  mac[4] = WINBORDER_MAC_SUFFIX_0;

  rc = esp_iface_mac_addr_set(mac, ESP_MAC_BT);
  if (rc != ESP_OK) {
    Serial.printf("[ble] !! failed to set custom MAC rc=%d, keeping factory address\n",
                  (int)rc);
    return;
  }
#if 1
  // Read the address back: a failed write leaves the old address in place
  // silently.
  uint8_t verify[6] = {0};
  esp_read_mac(verify, ESP_MAC_BT);
  Serial.printf("[ble] BLE address: factory %02X:%02X:%02X:%02X:%02X:%02X -> "
                "now %02X:%02X:%02X:%02X:%02X:%02X %s\n",
                orig[0], orig[1], orig[2], orig[3], orig[4], orig[5],
                verify[0], verify[1], verify[2], verify[3], verify[4], verify[5],
                memcmp(verify, mac, 6) == 0 ? "(applied)" : "(NOT applied)");
#else
  (void)orig;
#endif
#endif
}
static const char *DEVICE_NAME = WINBORDER_DEVICE_NAME;

// Serial baud rate, must match the host --baudrate.
static const uint32_t SERIAL_BAUD = 115200;

// Frame magic, identical to winborder/protocol.py.
static const uint8_t MAGIC0 = 0xA5;
static const uint8_t MAGIC1 = 0x5A;

// Maximum payload per frame, and it must match the host: a longer frame is
// rejected as an illegal length, and the byte-by-byte resynchronisation that
// follows swallows the next valid frame. Every deviceLog() message therefore has
// to stay within this length, which is why the status lines are sent as separate
// frames.
static const uint8_t MAX_PAYLOAD = 64;

// Heartbeat timeout: after this long without any host frame, all keys are forced
// released.
static const uint32_t HEARTBEAT_TIMEOUT_MS = 1500;

// Double-tap Ctrl detection window.
static const uint32_t CTRL_CTRL_WINDOW_MS = 400;

// Onboard status LED. Boards differ enough to need three cases:
//   - ESP32-S3: LED_BUILTIN is a synthetic pin number
//     (SOC_GPIO_PIN_COUNT + PIN_RGB_LED) denoting the onboard addressable RGB
//     LED. pinMode/digitalWrite cannot drive it; rgbLedWrite() is required.
//   - C3/C6 Supermini: a plain LED on GPIO8.
//   - Board without an LED: set STATUS_LED to -1.
#if defined(ARDUINO_ARCH_ESP32) && defined(RGB_BUILTIN) && defined(LED_BUILTIN) \
    && (LED_BUILTIN >= SOC_GPIO_PIN_COUNT)
#define WINBORDER_STATUS_LED_RGB 1
static const int STATUS_LED = -1;                  // no numeric pin used
#elif defined(LED_BUILTIN)
static const int STATUS_LED = LED_BUILTIN;
#else
static const int STATUS_LED = 8;
#endif

// Host -> device
enum HostMsg : uint8_t {
  MSG_PING = 0x01,
  MSG_VERSION_REQ = 0x02,
  MSG_STATE = 0x03,
  MSG_MOUSE_MOVE = 0x04,
  MSG_MOUSE_BUTTON = 0x05,
  MSG_MOUSE_WHEEL = 0x06,
  MSG_RESET = 0x07,
  MSG_CONFIG = 0x08,
  MSG_CONSUMER = 0x09,
};

// Device -> host
enum DevMsg : uint8_t {
  DEV_VERSION = 0x81,
  DEV_ACK = 0x82,
  DEV_NAK = 0x83,
  DEV_SWITCH_BACK = 0x84,
  DEV_KEY_ECHO = 0x85,
  DEV_LOG = 0x86,
};

static const uint8_t FW_MAJOR = 1, FW_MINOR = 0, FW_PATCH = 1;

// ==========================================================================
// HID report descriptor
// ==========================================================================
//
// Report layout, which must match winborder/protocol.py:
//   Report ID 1 (keyboard, 8B): [modifiers][reserved][k0..k5]
//   Report ID 2 (mouse, 4B):    [buttons][dx][dy][wheel]
//   Report ID 3 (consumer, 2B): [usage_lo][usage_hi]
//
static const uint8_t HID_REPORT_MAP[] = {
    // ---------------- Report ID 1: keyboard ----------------
    0x05, 0x01,        // Usage Page (Generic Desktop)
    0x09, 0x06,        // Usage (Keyboard)
    0xA1, 0x01,        // Collection (Application)
    0x85, 0x01,        //   Report ID (1)
    0x05, 0x07,        //   Usage Page (Keyboard/Keypad)
    0x19, 0xE0,        //   Usage Minimum (LeftControl)
    0x29, 0xE7,        //   Usage Maximum (Right GUI)
    0x15, 0x00,        //   Logical Minimum (0)
    0x25, 0x01,        //   Logical Maximum (1)
    0x75, 0x01,        //   Report Size (1)
    0x95, 0x08,        //   Report Count (8)
    0x81, 0x02,        //   Input (Data,Var,Abs)   <- modifier bitmap (1B)
    0x95, 0x01,        //   Report Count (1)
    0x75, 0x08,        //   Report Size (8)
    0x81, 0x01,        //   Input (Const)          <- reserved byte (1B)
    0x95, 0x05,        //   Report Count (5)
    0x75, 0x01,        //   Report Size (1)
    0x05, 0x08,        //   Usage Page (LEDs)
    0x19, 0x01,        //   Usage Minimum (Num Lock)
    0x29, 0x05,        //   Usage Maximum (Kana)
    0x91, 0x02,        //   Output (Data,Var,Abs)  <- LEDs, written back by the target
    0x95, 0x01,        //   Report Count (1)
    0x75, 0x03,        //   Report Size (3)
    0x91, 0x01,        //   Output (Const)
    0x95, 0x06,        //   Report Count (6)
    0x75, 0x08,        //   Report Size (8)
    0x15, 0x00,        //   Logical Minimum (0)
    0x25, 0x65,        //   Logical Maximum (101)
    0x05, 0x07,        //   Usage Page (Keyboard/Keypad)
    0x19, 0x00,        //   Usage Minimum (0)
    0x29, 0x65,        //   Usage Maximum (101)
    0x81, 0x00,        //   Input (Data,Array)     <- 6 key slots (6B)
    0xC0,              // End Collection

    // ---------------- Report ID 2: mouse ----------------
    0x05, 0x01,        // Usage Page (Generic Desktop)
    0x09, 0x02,        // Usage (Mouse)
    0xA1, 0x01,        // Collection (Application)
    0x85, 0x02,        //   Report ID (2)
    0x09, 0x01,        //   Usage (Pointer)
    0xA1, 0x00,        //   Collection (Physical)
    0x05, 0x09,        //     Usage Page (Button)
    0x19, 0x01,        //     Usage Minimum (Button 1)
    0x29, 0x05,        //     Usage Maximum (Button 5)
    0x15, 0x00,        //     Logical Minimum (0)
    0x25, 0x01,        //     Logical Maximum (1)
    0x95, 0x05,        //     Report Count (5)
    0x75, 0x01,        //     Report Size (1)
    0x81, 0x02,        //     Input (Data,Var,Abs)  <- button bitmap (1B)
    0x95, 0x01,        //     Report Count (1)
    0x75, 0x03,        //     Report Size (3)
    0x81, 0x01,        //     Input (Const)         <- 3 padding bits
    0x05, 0x01,        //     Usage Page (Generic Desktop)
    0x09, 0x30,        //     Usage (X)
    0x09, 0x31,        //     Usage (Y)
    0x09, 0x38,        //     Usage (Wheel)
    0x15, 0x81,        //     Logical Minimum (-127)
    0x25, 0x7F,        //     Logical Maximum (127)
    0x75, 0x08,        //     Report Size (8)
    0x95, 0x03,        //     Report Count (3)
    0x81, 0x06,        //     Input (Data,Var,Rel)  <- dx, dy, wheel (3B)
    // Do not add a placeholder byte here. The descriptor declares a payload of
    // buttons(1) + X(1) + Y(1) + wheel(1) = 4 bytes and the notification carries
    // Report ID(1) + 4 bytes = 5. The declared payload length must equal the
    // number of bytes after the report ID in the notification; a placeholder
    // makes the lengths disagree and the report is dropped silently.
    0xC0,              //   End Collection
    0xC0,              // End Collection

    // ---------------- Report ID 3: consumer control ----------------
    0x05, 0x0C,        // Usage Page (Consumer)
    0x09, 0x01,        // Usage (Consumer Control)
    0xA1, 0x01,        // Collection (Application)
    0x85, 0x03,        //   Report ID (3)
    0x15, 0x00,        //   Logical Minimum (0)
    0x26, 0xFF, 0x03,  //   Logical Maximum (1023)
    0x19, 0x00,        //   Usage Minimum (0)
    0x2A, 0xFF, 0x03,  //   Usage Maximum (1023)
    0x75, 0x10,        //   Report Size (16)
    0x95, 0x01,        //   Report Count (1)
    0x81, 0x00,        //   Input (Data,Array,Abs) <- 16 bit usage (2B)
    0xC0,              // End Collection
};

// bcdHID 1.11 / bCountryCode 0 / flags: remote wake supported.
static const uint8_t HID_INFO[] = {0x11, 0x01, 0x00, 0x02};

// Standard BLE HID UUIDs.
static NimBLEUUID UUID_HID_SERVICE("1812");
static NimBLEUUID UUID_HID_INFO("2A4A");
static NimBLEUUID UUID_REPORT_MAP("2A4B");
static NimBLEUUID UUID_HID_CONTROL("2A4C");
static NimBLEUUID UUID_REPORT("2A4D");
static NimBLEUUID UUID_REPORT_REFERENCE("2908");

// ==========================================================================
// Global state
// ==========================================================================
struct KeyState {
  uint8_t modifiers = 0;
  uint8_t keys[6] = {0, 0, 0, 0, 0, 0};
  uint8_t buttons = 0;
  uint16_t consumer = 0;
};

static KeyState g_state;
static KeyState g_sent;                    // last state actually sent, for idempotent de-duplication

static NimBLECharacteristic *g_reportKbd = nullptr;
static NimBLECharacteristic *g_reportMouse = nullptr;
static NimBLECharacteristic *g_reportConsumer = nullptr;

static volatile bool g_connected = false;
static volatile bool g_subscribed = false;
static volatile int g_reportSubs = 0;      // number of subscribed Report CCCDs
static volatile uint8_t g_subMask = 0;     // per-report subscription bitmap
static uint32_t g_lastHostFrame = 0;
static uint32_t g_lastCtrlDown = 0;
static bool g_linkAlive = false;
static uint32_t g_lastLedToggle = 0;
static uint32_t g_framesFromHost = 0;
static uint32_t g_badFrames = 0;
// Last negotiated connection parameters, reported with the status line so the
// peer's interval / MTU / bonding state can be checked.
static uint16_t g_lastInterval = 0;
static uint16_t g_lastMtu = 0;
static bool g_lastBonded = false;
static bool g_lastEncrypted = false;

// Serial frame parser state.
static uint8_t rxType = 0, rxLen = 0, rxIdx = 0, rxSum = 0;
static uint8_t rxPayload[MAX_PAYLOAD];
enum RxState { RX_MAGIC0, RX_MAGIC1, RX_TYPE, RX_LEN, RX_PAYLOAD, RX_SUM };
static RxState rxState = RX_MAGIC0;

// ==========================================================================
// Status LED
// ==========================================================================
// Slow blink = host not connected, solid = host connected, fast blink = input is
// flowing. The S3 onboard LED is an addressable RGB LED driven with
// rgbLedWrite(); a plain LED uses digitalWrite().
static void updateStatusLed() {
#if defined(WINBORDER_STATUS_LED_RGB)
  static bool on = false;
  uint32_t now = millis();
  static uint32_t last = 0;
  if (!g_connected) {
    if (now - last > 500) { last = now; on = !on; }
    rgbLedWrite(RGB_BUILTIN, on ? 24 : 0, 0, on ? 60 : 0);        // slow blue blink
  } else if (now - g_lastHostFrame < 100) {
    // Data is flowing: green.
    rgbLedWrite(RGB_BUILTIN, 0, 40, 0);
  } else {
    rgbLedWrite(RGB_BUILTIN, 0, 16, 0);                          // solid green
  }
#elif STATUS_LED >= 0
  uint32_t now = millis();
  if (!g_connected) {
    if (now - g_lastLedToggle > 500) {
      g_lastLedToggle = now;
      digitalWrite(STATUS_LED, !digitalRead(STATUS_LED));
    }
  } else if (now - g_lastHostFrame < 100) {
    digitalWrite(STATUS_LED, (now / 50) % 2);                    // fast blink
  } else {
    digitalWrite(STATUS_LED, HIGH);                              // solid
  }
#else
  (void)0;                                                       // no LED on this board
#endif
}

// ==========================================================================
// Host link helpers
// ==========================================================================
static void sendFrame(uint8_t type, const uint8_t *payload, uint8_t len) {
  uint8_t checksum = (uint8_t)(type + len);
  for (uint8_t i = 0; i < len; i++) checksum = (uint8_t)(checksum + payload[i]);
  Serial.write(MAGIC0);
  Serial.write(MAGIC1);
  Serial.write(type);
  Serial.write(len);
  if (len) Serial.write(payload, len);
  Serial.write(checksum);
}

static void sendNak(uint8_t type, uint8_t reason) {
  uint8_t p[2] = {type, reason};
  sendFrame(DEV_NAK, p, 2);
}

static void deviceLog(const char *text) {
  sendFrame(DEV_LOG, (const uint8_t *)text, (uint8_t)strlen(text));
}

// ==========================================================================
// HID reporting
// ==========================================================================
static uint8_t clamp127(int v) {
  if (v > 127) return 127;
  if (v < -127) return (uint8_t)(-127);
  return (uint8_t)(int8_t)v;
}

// ==========================================================================
// HID report format
// ==========================================================================
// Report data must NOT begin with a Report ID byte. BLE HID carries reports in
// characteristic values and the host resolves the report ID from the
// characteristic's Report Reference descriptor (0x2908); the "first byte is the
// report ID" rule belongs to USB HID transfers and does not apply here. Prefixing
// the data shifts every field by one byte and the host drops the report, which
// shows up as a silent keyboard and a mouse moving in the wrong direction.
//
// This file therefore defines no REPORT_ID_* constants, and every report length
// equals the payload length declared in HID_REPORT_MAP: keyboard 8, mouse 4,
// consumer 2 bytes.

// Notification send counters. They separate the layers that can lose a report,
// because all of them look identical from outside (no pointer on the target):
//   tx_try does not grow              -> the host is not sending input
//   tx_try grows, tx_ok does not      -> the stack refused the notification
//   tx_ok grows but the peer ignores  -> the report reached the link
static volatile uint32_t g_txTry = 0;static volatile uint32_t g_txOk = 0;
static volatile uint32_t g_txSkipNoConn = 0;
// Notifications the stack refused. A refused report is not a delivered one, so
// the state it carried stays pending and is sent again.
static volatile uint32_t g_txDropped = 0;

#if 1
// Last received key state, reported through deviceLog (see MSG_STATE).
static char g_keyLog[96] = {0};
#endif

static bool notify(NimBLECharacteristic *ch, const uint8_t *data, uint16_t len) {
  if (!g_connected || !g_subscribed || ch == nullptr) {
    g_txSkipNoConn++;
    return false;
  }
  g_txTry++;
  ch->setValue(data, len);
  if (ch->notify()) {
    g_txOk++;
    return true;
  }
  // A refused notification is congestion, not a delivery. The caller must not
  // record the state as sent, or the target keeps a state that was never
  // reported and the two sides disagree about which keys are down.
  g_txDropped++;
  return false;
}
// The keyboard report is sent only when the state changes; an idempotent
// snapshot makes that check trivial.
static void flushKeyboard(bool force = false) {
  if (!force &&
      g_state.modifiers == g_sent.modifiers &&
      memcmp(g_state.keys, g_sent.keys, 6) == 0) {
    return;
  }
  // 8 bytes = {modifiers, reserved, keys[6]}, with no Report ID.
  uint8_t r[8] = {g_state.modifiers, 0x00,
                  g_state.keys[0], g_state.keys[1], g_state.keys[2],
                  g_state.keys[3], g_state.keys[4], g_state.keys[5]};
  if (!notify(g_reportKbd, r, sizeof(r))) {
    return;                       // retried on the next flush, state unchanged
  }
  g_sent.modifiers = g_state.modifiers;
  memcpy(g_sent.keys, g_state.keys, 6);
}

// ==========================================================================
// Mouse movement coalescing
// ==========================================================================
// The host sends MSG_MOUSE_MOVE at about 100Hz, and one message can be split into
// up to 8 reports to stay within the HID limit of +/-127 per report. Sending one
// report per slice would require up to 800 notifications per second, while a
// 30ms connection interval carries roughly 33, so notifications would pile up in
// the stack and movement would lag, jump, or destabilise the link.
//
// Relative deltas are additive, so merging several small deltas into one report
// is semantically equivalent and loses nothing. Button and wheel events are order
// sensitive, so they flush the accumulated delta first and are then sent alone.
static int32_t g_pendDx = 0;
static int32_t g_pendDy = 0;
static uint32_t g_lastMouseFlush = 0;
// Reporting period. Too short and the link is overloaded again, too long and the
// pointer feels sluggish. 8ms (125Hz) matches the host sample rate, and each
// period emits only one or two reports, which fits the link capacity.
static const uint32_t MOUSE_FLUSH_INTERVAL_MS = 8;

static void flushMouseMove(bool force = false) {
  uint32_t now = millis();
  if (!force && (now - g_lastMouseFlush) < MOUSE_FLUSH_INTERVAL_MS) return;
  if (g_pendDx == 0 && g_pendDy == 0) return;

  g_lastMouseFlush = now;
  int32_t dx = g_pendDx;
  int32_t dy = g_pendDy;
  g_pendDx = 0;
  g_pendDy = 0;

  // Still bound to +/-127 per HID report, so the accumulated delta is sliced.
  // Unlike slicing per serial message, slicing on a fixed period bounds the total
  // number of reports that can be emitted.
  int guard = 0;
  while ((dx != 0 || dy != 0) && guard++ < 8) {
    int sx = dx > 127 ? 127 : (dx < -127 ? -127 : (int)dx);
    int sy = dy > 127 ? 127 : (dy < -127 ? -127 : (int)dy);
    // 4 bytes = {buttons, dx, dy, wheel}, with no Report ID. The length must
    // equal the payload length declared in the descriptor.
    uint8_t r[4] = {g_state.buttons,
                    (uint8_t)(int8_t)sx, (uint8_t)(int8_t)sy, 0x00};
    notify(g_reportMouse, r, sizeof(r));
    dx -= sx;
    dy -= sy;
  }
}

static void sendMouseMove(int dx, int dy) {
  // Accumulate only; flushMouseMove() does the sending on its fixed period.
  g_pendDx += dx;
  g_pendDy += dy;
}

static void sendWheel(int vwheel) {
  // The wheel shares the mouse report with X/Y, so it could be sent in the same
  // notification; sending it alone keeps ordering predictable. The accumulated
  // delta is flushed first so that pointer motion keeps its order.
  flushMouseMove(true);
  uint8_t r[4] = {g_state.buttons, 0x00, 0x00, (uint8_t)(int8_t)vwheel};
  notify(g_reportMouse, r, sizeof(r));
}

static void flushButtons(bool force = false) {
  if (!force && g_state.buttons == g_sent.buttons) return;
  // A button change must be visible immediately, so pending motion goes first.
  flushMouseMove(true);
  uint8_t r[4] = {g_state.buttons, 0x00, 0x00, 0x00};
  if (!notify(g_reportMouse, r, sizeof(r))) {
    return;                       // retried on the next flush, state unchanged
  }
  g_sent.buttons = g_state.buttons;
}

static void flushConsumer(bool force = false) {
  if (!force && g_state.consumer == g_sent.consumer) return;
  // 2 bytes = 16 bit usage, with no Report ID.
  uint8_t r[2] = {(uint8_t)(g_state.consumer & 0xFF),
                  (uint8_t)(g_state.consumer >> 8)};
  if (!notify(g_reportConsumer, r, sizeof(r))) {
    return;                       // retried on the next flush, state unchanged
  }
  g_sent.consumer = g_state.consumer;
}

// Release everything: used on link loss, RESET, and mode switches.
static void releaseAll() {
  memset(g_state.keys, 0, sizeof(g_state.keys));
  g_state.modifiers = 0;
  g_state.buttons = 0;
  g_state.consumer = 0;
  // Drop unsent motion: releasing means "stop all input", and a residual delta
  // would keep pushing the cursor in the reports that follow.
  g_pendDx = 0;
  g_pendDy = 0;
  flushKeyboard(true);
  flushButtons(true);
  flushConsumer(true);
}

// ==========================================================================
// GATT callbacks
// ==========================================================================
// Subscription callbacks attach to the *characteristic*, not to the server
// (NimBLE-Arduino API); attaching them elsewhere fails with "marked override, but
// does not override". They matter because a notification is only sent once the
// peer has subscribed to the Report characteristic's CCCD, and because they act
// as a gate during service discovery: notifications sent while the peer is
// walking the attribute table can abort that walk, so nothing is sent before
// subscription completes.

// Report Map reads are counted: a HID host cannot classify the device without
// reading the descriptor first.
static NimBLECharacteristic *g_reportMapChr = nullptr;
static volatile uint32_t g_reportMapReads = 0;

class ReportMapCallbacks : public NimBLECharacteristicCallbacks {
  // Note the signature: NimBLE 2.x onRead takes (characteristic, connection
  // info) with no NimBLEAttValue&, otherwise the compiler reports
  // "marked 'override', but does not override".
  void onRead(NimBLECharacteristic *ch, NimBLEConnInfo &info) override {
    (void)info;
    g_reportMapReads++;
#if 1
    // Every HID host reads the Report Map (0x2A4B) as the first step of
    // classifying the device; without that read it is not treating the board as
    // a HID peripheral at all.
    Serial.printf("[ble] peer read the Report Map (#%lu, handle=%d)\n",
                  (unsigned long)g_reportMapReads,
                  ch != nullptr ? (int)ch->getHandle() : -1);
#endif
  }
};
static ReportMapCallbacks g_reportMapCallbacks;

class ReportCallbacks : public NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic *ch, NimBLEConnInfo &info,
                   uint16_t subValue) override {
    (void)info;
    // 0x0001 = notifications, 0x0002 = indications, 0 = unsubscribe.
    bool on = (subValue & 0x0001) != 0;
    if (on) {
      g_reportSubs++;
    } else if (g_reportSubs > 0) {
      g_reportSubs--;
    }
    g_subscribed = g_reportSubs > 0;
#if 1
    Serial.printf("[ble] report subscribe=%d handle=%d subs=%d\n",
                  (int)on, ch != nullptr ? (int)ch->getHandle() : 0,
                  g_reportSubs);
#else
    (void)ch;
#endif
    if (g_subscribed) releaseAll();
  }
};

// Static instance: characteristics hold a pointer, so the object must outlive
// them.
static ReportCallbacks g_reportCallbacks;

// ==========================================================================
// Host frame handling
// ==========================================================================
static void handleHostFrame(uint8_t type, const uint8_t *p, uint8_t len) {
  g_framesFromHost++;
  g_lastHostFrame = millis();
  if (!g_linkAlive) {
    g_linkAlive = true;
    deviceLog("link up");
  }

  switch (type) {
    case MSG_PING:
      break;

    case MSG_VERSION_REQ: {
      uint8_t v[3] = {FW_MAJOR, FW_MINOR, FW_PATCH};
      sendFrame(DEV_VERSION, v, 3);
      break;
    }

    case MSG_STATE: {
      if (len != 8) { sendNak(type, 0x01); return; }
      uint8_t mods = p[0];

      // Double-tap Ctrl switches back: detect a new press of a Ctrl bit.
      bool ctrlNow = (mods & 0x11) != 0;          // left Ctrl (0x01) or right Ctrl (0x10)
      bool ctrlWas = (g_state.modifiers & 0x11) != 0;
      if (ctrlNow && !ctrlWas) {
        uint32_t now = millis();
        if (g_lastCtrlDown != 0 && (now - g_lastCtrlDown) <= CTRL_CTRL_WINDOW_MS) {
          g_lastCtrlDown = 0;
          // The gesture is not forwarded to the target; the host is asked to
          // switch back instead.
          uint8_t how = 0;
          sendFrame(DEV_SWITCH_BACK, &how, 1);
          deviceLog("switch back requested");
          return;
        }
        g_lastCtrlDown = now;
      } else if (!ctrlNow) {
        if (g_lastCtrlDown != 0 && (millis() - g_lastCtrlDown) > CTRL_CTRL_WINDOW_MS) {
          g_lastCtrlDown = 0;
        }
      }

      g_state.modifiers = mods;
      memcpy(g_state.keys, p + 2, 6);
#if 1
      // Echo the received key state to the host. The frame counter alone does not
      // show whether the frames carry real key data, so the modifier and key
      // bytes are reported as received.
      if (mods != 0 || p[2] != 0 || p[3] != 0 || p[4] != 0 ||
          p[5] != 0 || p[6] != 0 || p[7] != 0) {
        snprintf(g_keyLog, sizeof(g_keyLog), "key in mod=%02X keys=%02X %02X %02X %02X %02X %02X",
                 mods, p[2], p[3], p[4], p[5], p[6], p[7]);
        deviceLog(g_keyLog);
        Serial.printf("[winborder] %s\n", g_keyLog);
      }
#endif
      flushKeyboard();
      break;
    }

    case MSG_MOUSE_MOVE: {
      if (len != 4) { sendNak(type, 0x01); return; }
      int16_t dx = (int16_t)(p[0] | (p[1] << 8));
      int16_t dy = (int16_t)(p[2] | (p[3] << 8));
      // The HID limit is +/-127 per report; the host already slices, this is a
      // second guard.
      int guard = 0;
      while ((dx != 0 || dy != 0) && guard++ < 8) {
        int sx = dx > 127 ? 127 : (dx < -127 ? -127 : dx);
        int sy = dy > 127 ? 127 : (dy < -127 ? -127 : dy);
        sendMouseMove(sx, sy);
        dx -= sx;
        dy -= sy;
      }
      break;
    }

    case MSG_MOUSE_BUTTON:
      if (len != 1) { sendNak(type, 0x01); return; }
      g_state.buttons = p[0];
      flushButtons();
#if 1
      // A button the target still holds turns every following move into a drag,
      // so the value is reported whenever it changes rather than only in the
      // periodic line.
      {
        char line[24];
        snprintf(line, sizeof(line), "btn=%02X", (unsigned)g_state.buttons);
        deviceLog(line);
      }
#endif
      break;

    case MSG_MOUSE_WHEEL:
      if (len != 2) { sendNak(type, 0x01); return; }
      // Vertical first; horizontal is used only when vertical is zero, because
      // the descriptor exposes a single wheel field.
      if ((int8_t)p[0] != 0) sendWheel((int8_t)p[0]);
      else if ((int8_t)p[1] != 0) sendWheel((int8_t)p[1]);
      break;

    case MSG_CONSUMER:
      if (len != 2) { sendNak(type, 0x01); return; }
      g_state.consumer = (uint16_t)(p[0] | (p[1] << 8));
      flushConsumer();
      break;

    case MSG_RESET:
      releaseAll();
      break;

    case MSG_CONFIG:
      if (len != 6) { sendNak(type, 0x01); return; }
      deviceLog("config accepted");
      break;

    default:
      sendNak(type, 0x02);
      return;                                   // no ACK for unknown types
  }

  uint8_t echo = type;
  sendFrame(DEV_ACK, &echo, 1);
}

// ==========================================================================
// Serial frame parser
// ==========================================================================
static void pollSerial() {
  while (Serial.available() > 0) {
    uint8_t b = (uint8_t)Serial.read();
    switch (rxState) {
      case RX_MAGIC0:
        if (b == MAGIC0) rxState = RX_MAGIC1;
        break;
      case RX_MAGIC1:
        rxState = (b == MAGIC1) ? RX_TYPE : RX_MAGIC0;
        break;
      case RX_TYPE:
        rxType = b;
        rxSum = b;
        rxState = RX_LEN;
        break;
      case RX_LEN:
        rxLen = b;
        rxSum = (uint8_t)(rxSum + b);
        if (rxLen > MAX_PAYLOAD) { g_badFrames++; rxState = RX_MAGIC0; break; }
        rxIdx = 0;
        rxState = (rxLen == 0) ? RX_SUM : RX_PAYLOAD;
        break;
      case RX_PAYLOAD:
        rxPayload[rxIdx++] = b;
        rxSum = (uint8_t)(rxSum + b);
        if (rxIdx >= rxLen) rxState = RX_SUM;
        break;
      case RX_SUM:
        if (b == rxSum) handleHostFrame(rxType, rxPayload, rxLen);
        else g_badFrames++;
        rxState = RX_MAGIC0;
        break;
    }
  }
}

// ==========================================================================
// BLE service setup (NimBLE-Arduino >= 2.0 API)
// ==========================================================================
static void addReportCharacteristic(NimBLEService *svc, uint8_t reportId,
                                   NimBLECharacteristic **slot) {
  NimBLECharacteristic *ch = svc->createCharacteristic(
      UUID_REPORT, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY);
  if (ch == nullptr) {
    Serial.printf("[gatt] !! failed to create Report %d\n", (int)reportId);
    return;
  }
  uint8_t ref[2] = {reportId, 0x01};          // 0x01 = input report
  NimBLEDescriptor *d = ch->createDescriptor(UUID_REPORT_REFERENCE,
                                             NIMBLE_PROPERTY::READ);
  if (d == nullptr) {
    Serial.printf("[gatt] !! failed to create the descriptor for Report %d\n",
                  (int)reportId);
  } else {
    d->setValue(ref, 2);
  }
  ch->setCallbacks(&g_reportCallbacks);
  *slot = ch;
#if 1
  Serial.printf("[gatt] Report %d created, handle=%d\n", (int)reportId,
                (int)ch->getHandle());
#endif
}

// ==========================================================================
// HID service, built with the library's NimBLEHIDDevice
// ==========================================================================
// The HID layer must not be assembled by hand. A hand-written version of this
// service (an own 0x1812 service, six characteristics, and hand-attached Report
// Reference descriptors) connected, subscribed, and notified normally, yet the
// keyboard and mouse produced no input on the target. Those details are what the
// library implementation already gets right:
//   - Report characteristic values do not carry a Report ID byte, and the ID
//     declared by 0x85 in the descriptor occupies no payload bits;
//   - the payload length declared in the descriptor must equal the number of
//     bytes after the report ID in the notification;
//   - GAP Appearance must be 0x03C2 (HID Mouse) rather than 0x03C1 (Keyboard);
//     it decides whether iOS treats the device as a pointer.
static NimBLEHIDDevice *g_hid = nullptr;

static void setupHidService(NimBLEServer *server) {
  g_hid = new NimBLEHIDDevice(server);
  if (g_hid == nullptr) {
    Serial.println("[gatt] !! failed to create NimBLEHIDDevice");
    return;
  }

  // Three input reports. The argument is the Report ID declared in the report
  // descriptor, not a byte in the report data.
  g_reportKbd = g_hid->getInputReport(1);        // keyboard, Report ID 1
  g_reportMouse = g_hid->getInputReport(2);      // mouse, Report ID 2
  g_reportConsumer = g_hid->getInputReport(3);   // consumer, Report ID 3

  g_hid->setReportMap((uint8_t *)HID_REPORT_MAP, sizeof(HID_REPORT_MAP));
  g_hid->setManufacturer("Winborder");
  g_hid->setPnp(0x02, 0x02E5, 0x0001, 0x0100);
  g_hid->setHidInfo(0x00, 0x02);        // remote wake supported

  g_hid->setBatteryLevel(100, false);   // battery service, read by iOS for HID peripherals

  // Subscription state and Report Map reads are both tracked; the status line
  // reports them as sub= and rmap=.
  if (g_reportKbd) g_reportKbd->setCallbacks(&g_reportCallbacks);
  if (g_reportMouse) g_reportMouse->setCallbacks(&g_reportCallbacks);
  if (g_reportConsumer) g_reportConsumer->setCallbacks(&g_reportCallbacks);

  NimBLECharacteristic *map = g_hid->getReportMap();
  if (map != nullptr) {
    map->setCallbacks(&g_reportMapCallbacks);
    g_reportMapChr = map;
  }

#if 1
  Serial.printf("[gatt] HID service (library) ready: kbd=%d mouse=%d consumer=%d reportMap=%d\n",
                g_reportKbd != nullptr, g_reportMouse != nullptr,
                g_reportConsumer != nullptr, map != nullptr);
#endif

  // Self-check: the library creates one characteristic per Report ID in the
  // descriptor, so a null slot means the descriptor and the getInputReport()
  // arguments disagree. That must be detected here, otherwise it only shows up
  // later as "the link is fine but there is no input".
  if (g_reportKbd == nullptr || g_reportMouse == nullptr ||
      g_reportConsumer == nullptr) {
    Serial.println("[gatt] !! an input report characteristic is missing - check "
                   "that the Report IDs in the descriptor match getInputReport()");
  } else {
#if 1
    Serial.printf("[gatt] report handles: kbd=%d mouse=%d consumer=%d\n",
                  (int)g_reportKbd->getHandle(), (int)g_reportMouse->getHandle(),
                  (int)g_reportConsumer->getHandle());
#endif
  }
}

// ==========================================================================
// Experimental switch: append a dummy service to the attribute table
// ==========================================================================
// Hypothesis under test: a client drops the *last* service of a service
// discovery response because NimBLE reports its end_handle as the 0xFFFF sentinel
// when the service is last in the attribute list (ble_att_svr.c: "We have
// reached the end of the attribute list. Indicate an end handle of 0xffff"). The
// HID service is always last, so it would be the one dropped, while GAP and GATT
// carry real end handles.
//
// With the switch on, the dummy service occupies the last slot and the HID
// service gets a real end handle. If a peer that previously missed the HID
// service then sees it, the hypothesis holds.
#define WINBORDER_TAIL_DUMMY_SERVICE 0

// ==========================================================================
// Experimental switch: create the HID service first
// ==========================================================================
// Distinguishes two explanations for a peer that never discovers the HID
// service:
//   A) the client drops the last service because of the 0xFFFF end_handle
//      sentinel;
//   B) the client drops any service registered after GATT.
// Creating HID before GAP and GATT changes the order to HID / GAP / GATT: if the
// peer then sees HID, the problem is specific to the last service; if it still
// does not, the position relative to GATT is what matters.
// This requires NimBLEServer::addService(), which only accepts a service that has
// not been started yet, so the HID service must not call start() itself.
#define WINBORDER_HID_FIRST 0

// Dummy service: one harmless read-only characteristic, present only to take the
// last service slot.
// The UUID must be given in full 128 bit form. A short form such as "FFF0" is
// registered as a 16 bit UUID, which collides with the derived 16 bit UUIDs of
// the services before it and produces uuid16=0x0000 - an invalid primary service
// UUID in the response - after which clients degrade instead of ignoring the
// extra service.
static void setupTailService(NimBLEServer *server) {
  NimBLEService *svc = server->createService(
      NimBLEUUID("0000fff0-0000-1000-8000-00805f9b34fb"));
  if (svc == nullptr) {
    Serial.println("[gatt] !! failed to create the dummy service");
    return;
  }
  NimBLECharacteristic *ch = svc->createCharacteristic(
      NimBLEUUID("0000fff1-0000-1000-8000-00805f9b34fb"),
      NIMBLE_PROPERTY::READ);
  if (ch) {
    const uint8_t marker[4] = {'W', 'P', 'A', 'D'};
    ch->setValue(marker, sizeof(marker));
  }
  bool ok = svc->start();
#if 1
  Serial.printf("[gatt] dummy service (FFF0) start() = %s, handle=%d\n",
                ok ? "ok" : "FAILED", (int)svc->getHandle());
#else
  (void)ok;
#endif
}

class ServerCallbacks : public NimBLEServerCallbacks {
  void printConnParams(NimBLEConnInfo &info) {
    // Recorded so the status line can report them; no serial monitor needed.
    g_lastInterval = info.getConnInterval();
    g_lastMtu = info.getMTU();
    g_lastBonded = info.isBonded();
    g_lastEncrypted = info.isEncrypted();
#if 1
    // An ignored connection parameter request hurts pointer responsiveness, so
    // the negotiated values are printed for comparison. iOS requires an interval
    // of at least 15ms.
    Serial.printf("[ble] conn params: interval=%.2fms latency=%d timeout=%dms "
                  "mtu=%d bonded=%d encrypted=%d\n",
                  g_lastInterval * 1.25f,
                  (int)info.getConnLatency(), (int)info.getConnTimeout() * 10,
                  (int)g_lastMtu, (int)g_lastBonded, (int)g_lastEncrypted);
    char line[160];
    snprintf(line, sizeof(line),
             "connected interval=%.2fms latency=%d timeout=%dms mtu=%d bonded=%d enc=%d",
             g_lastInterval * 1.25f, (int)info.getConnLatency(),
             (int)info.getConnTimeout() * 10, (int)g_lastMtu,
             (int)g_lastBonded, (int)g_lastEncrypted);
    deviceLog(line);
#endif
  }

  void onConnect(NimBLEServer *server, NimBLEConnInfo &info) override {
    g_connected = true;
    g_subscribed = false;
    (void)server;
#if 1
    Serial.printf("[ble] connected: %s  handle=%d\n",
                  info.getAddress().toString().c_str(), (int)info.getConnHandle());
#endif
    // The connection parameters must stay within what iOS accepts:
    // interval 15..30ms (below 15ms, for example 7.5ms, is dropped), latency 0,
    // timeout 4s. NimBLE's updateConnParams unit is 1.25ms,
    // so 12 = 15ms and 24 = 30ms.
    server->updateConnParams(info.getConnHandle(), 12, 24, 0, 400);
    printConnParams(info);
  }

  void onDisconnect(NimBLEServer *server, NimBLEConnInfo &info, int reason) override {
    g_connected = false;
    g_subscribed = false;
    (void)server;
    (void)info;
#if 1
    Serial.printf("[ble] disconnected (reason=%d), re-advertising\n", reason);
#else
    (void)reason;
#endif
    NimBLEDevice::startAdvertising();
  }

  void onConnParamsUpdate(NimBLEConnInfo &info) override {
    printConnParams(info);
  }
};

// ==========================================================================
// GATT table dump
// ==========================================================================
// iOS subscribes to reports only after it recognises a complete HID service (HID
// Information / Report Map / a Report characteristic with NOTIFY); a missing
// element shows up only as sub=0, so the table is dumped in full.
#if 1
static void printGattTable() {
  // NimBLE's own dump lists every handle and UUID actually registered in the ATT
  // table and is the authoritative view. The NimBLEService object tree is only
  // the in-memory definition and does not prove that a peer can discover it.
  Serial.println("[gatt] ==== NimBLE local attribute table (authoritative) ====");
  ble_gatts_show_local();
  Serial.println("[gatt] ==== end of attribute table ====");

  Serial.println("[gatt] --- HID service attributes (object tree, informational) ---");
  NimBLEService *svc = NimBLEDevice::getServer()->getServiceByUUID(UUID_HID_SERVICE);
  if (svc == nullptr) {
    Serial.println("[gatt] !! HID service (0x1812) not found - firmware is broken");
    return;
  }
  Serial.printf("[gatt] service 0x1812  handle=%d\n", (int)svc->getHandle());
  auto chars = svc->getCharacteristics();
  for (auto *ch : chars) {
    uint16_t props = ch->getProperties();
    Serial.printf("[gatt]   characteristic %s  handle=%d  props=0x%02X [%s%s%s%s]\n",
                  ch->getUUID().toString().c_str(), (int)ch->getHandle(),
                  (unsigned)props,
                  (props & NIMBLE_PROPERTY::READ) ? "Read " : "",
                  (props & NIMBLE_PROPERTY::WRITE) ? "Write " : "",
                  (props & NIMBLE_PROPERTY::NOTIFY) ? "Notify " : "",
                  (props & NIMBLE_PROPERTY::INDICATE) ? "Indicate" : "");
  }
  Serial.printf("[gatt] HID service has %d characteristics\n", (int)chars.size());
}
#endif

static void startBle() {
#if 1
  // The compile time log level above is not enough on its own: ESP-IDF also
  // filters by tag at runtime (CONFIG_LOG_DEFAULT_LEVEL=1), so the NimBLE tag has
  // to be raised here. The port is switched to 921600 as well, because DEBUG
  // logging at 115200 blocks the main loop and delays HID notifications, which
  // would distort whatever is being observed.
  Serial.flush();
  Serial.begin(921600);
  esp_log_level_set("NimBLE", ESP_LOG_DEBUG);
  delay(50);
  Serial.println("[winborder] BLE debug logging enabled (NimBLE host stack, DEBUG level)");
#endif
  // The address must be changed before NimBLEDevice::init(), which starts the BLE
  // controller; once running, the interface address is fixed.
  applyCustomBleMac();

  NimBLEDevice::init(DEVICE_NAME);

#if WINBORDER_WIPE_BONDS_ON_BOOT
  // Drop all device-side bonds so the peer performs a full pairing again.
  // Together with a new address this makes the board a completely new device to
  // the peer.
  {
    int n = NimBLEDevice::getNumBonds();
    if (n > 0) {
      bool ok = NimBLEDevice::deleteAllBonds();
      Serial.printf("[ble] deleted %d old bond(s) (%s)\n", n,
                    ok ? "ok" : "FAILED");
    } else {
      Serial.println("[ble] no old bonds to delete");
    }
  }
#endif

#if 1
  // Bonds are stored on both sides, so a peer that still remembers a pairing
  // will start encryption with a key the device no longer has if this count is 0
  // here: encryption fails, the connection is rejected, and the peer has to be
  // forgotten before it can pair again. That is the failure
  // WINBORDER_WIPE_BONDS_ON_BOOT=1 produces.
  Serial.printf("[ble] stored bonds: %d\n", NimBLEDevice::getNumBonds());
#endif

  NimBLEDevice::setPower(9);                   // +9dBm, ample for a normal room

  // iOS is strict about HID peripheral security and expects pairing with bonding
  // (Just Works is sufficient); without it, connections commonly drop as soon as
  // data flows, or reports never arrive.
  //   bonding=true -> long term keys are established, which is how iOS qualifies
  //                   the device as a real HID peripheral
  //   mitm=false   -> no input/output capability, so Just Works with no code to
  //                   type on the target
  //   sc=true      -> LE Secure Connections, required by iOS
  NimBLEDevice::setSecurityAuth(true, false, true);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);

  NimBLEServer *server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  setupHidService(server);

#if WINBORDER_TAIL_DUMMY_SERVICE
  setupTailService(server);
#endif

  // The GATT services must be started, otherwise a connected peer discovers
  // nothing.
  if (!server->start()) {
    Serial.println("[gatt] !! NimBLEServer::start() failed");
  }
  // The NimBLEHIDDevice services are started after server->start().
  if (g_hid != nullptr) {
    g_hid->startServices();
#if 1
    Serial.println("[gatt] HID services started (startServices)");
#endif
  }

  // The device name goes into both the advertising packet and the scan response:
  // the advertising packet is limited to 31 bytes, and carrying the name in the
  // scan response as well makes discovery more reliable on iOS.
  NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
  // GAP Appearance must be 0x03C2 (HID Mouse), not 0x03C1 (HID Keyboard). This
  // field is the authoritative device class (Apple kBluetoothGAPAppearance*), and
  // it is what decides whether iOS shows a pointer: with Keyboard, iOS received
  // the reports and stayed subscribed (sub=3, tx_ok growing) but never displayed
  // a cursor. The keyboard collection in the report descriptor keeps working
  // regardless.
  adv->setAppearance(0x03C2);                 // HID Mouse
  adv->addServiceUUID(UUID_HID_SERVICE);
  adv->enableScanResponse(true);
  adv->setName(DEVICE_NAME);
  adv->setMinInterval(160);                   // 100ms (unit 0.625ms)
  adv->setMaxInterval(320);                   // 200ms
  adv->start();
#if 1
  Serial.printf("[ble] advertising as \"%s\" (bonding + Secure Connections enabled)\n",
                DEVICE_NAME);
  // Dump the bytes actually being advertised. If neither the advertising packet
  // nor the scan response carries 0x1812, a peer cannot even tell that this is a
  // HID device, which is a separate question from whether the GATT table contains
  // the service. NimBLEAdvertising only exposes the advertising packet; the scan
  // response contents cannot be read back.
  {
    std::vector<uint8_t> advData = adv->getAdvertisementData().getPayload();
    Serial.printf("[ble] advertising packet (%uB):", (unsigned)advData.size());
    for (uint8_t c : advData) Serial.printf(" %02X", c);
    Serial.println();
    bool hasHid = false, hasName = false;
    for (size_t i = 0; i + 1 < advData.size(); ++i) {
      if (advData[i] == 0x12 && advData[i + 1] == 0x18) hasHid = true;
    }
    std::string advStr(advData.begin(), advData.end());
    hasName = advStr.find(DEVICE_NAME) != std::string::npos;
    Serial.printf("[ble] in advertising packet: HID service UUID (0x1812)=%s, name=%s\n",
                  hasHid ? "yes" : "no",
                  hasName ? "yes" : "no (expected in the scan response)");
  }
  printGattTable();
#endif
}

// ==========================================================================
// setup / loop
// ==========================================================================
void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);

#if !defined(WINBORDER_STATUS_LED_RGB) && STATUS_LED >= 0
  pinMode(STATUS_LED, OUTPUT);
  digitalWrite(STATUS_LED, LOW);
#endif

#if 1
  Serial.println();
  Serial.printf("[winborder] bridge firmware v%d.%d.%d\n", FW_MAJOR, FW_MINOR, FW_PATCH);
#if defined(WINBORDER_STATUS_LED_RGB)
  Serial.println("[winborder] onboard RGB status LED enabled (blue=waiting, solid green=linked)");
#endif
  Serial.println("[winborder] waiting for the host (python -m winborder)...");
#endif

  startBle();
  g_lastHostFrame = millis();
  g_lastLedToggle = millis();
}

void loop() {
  pollSerial();

  // Emit accumulated mouse motion on a fixed period. This has to be driven from
  // loop(): serial messages arrive in bursts at about 100Hz and a single message
  // can split into 8 reports, so only time-sliced sending keeps the BLE
  // notification rate within the link capacity.
  flushMouseMove();
  // Also driven from here, so a report the stack refused is retried even when
  // no further frame arrives to change the state.
  flushKeyboard();
  flushButtons();
  flushConsumer();

  uint32_t now = millis();

  // Heartbeat loss protection.
  if (g_linkAlive && (now - g_lastHostFrame) > HEARTBEAT_TIMEOUT_MS) {
    g_linkAlive = false;
    releaseAll();
    Serial.println("[winborder] host heartbeat timeout, released all keys");
  }

  updateStatusLed();

#if 1
  // Status is reported every 5s, both on the raw serial port and to the host.
  // The serial port is exclusive, so forwarding through the host is the only way
  // to see sub= - the one indicator of whether the target really subscribed to the
  // HID reports - while the host is running.
  static uint32_t lastReport = 0;
  if (now - lastReport > 5000) {
    lastReport = now;
    char line[160];
    // Separate frames: MAX_PAYLOAD is 64 bytes and a single combined line would
    // be dropped by the host.
    snprintf(line, sizeof(line), "ble=%d sub=%d host=%d frames=%lu bad=%lu",
             (int)g_connected, (int)g_reportSubs, (int)g_linkAlive,
             (unsigned long)g_framesFromHost, (unsigned long)g_badFrames);
    Serial.printf("[winborder] %s\n", line);
    deviceLog(line);

    snprintf(line, sizeof(line), "params interval=%.1fms mtu=%d bonded=%d enc=%d",
             g_lastInterval * 1.25f, (int)g_lastMtu,
             (int)g_lastBonded, (int)g_lastEncrypted);
    Serial.printf("[winborder] %s\n", line);
    deviceLog(line);

    // Report transmission counters. rmap=0 while connected means the peer is not
    // treating the board as a HID device. Growing tx_try/tx_ok mean the reports
    // did leave over BLE.
    snprintf(line, sizeof(line),
             "rmap=%lu tx_try=%lu tx_ok=%lu tx_skip=%lu tx_drop=%lu",
             (unsigned long)g_reportMapReads,
             (unsigned long)g_txTry, (unsigned long)g_txOk,
             (unsigned long)g_txSkipNoConn, (unsigned long)g_txDropped);
    Serial.printf("[winborder] %s\n", line);
    deviceLog(line);
  }
#endif

  delay(1);
}
