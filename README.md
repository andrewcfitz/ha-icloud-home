# iCloud Home Address

A Home Assistant integration with one job: write the **Home** address on an iCloud contact (normally your own "My Card"). Apple uses that address as "Home" in Maps, AutoFill, Siri, and Find My suggestions.

Built for full-time RVers. Pair it with whatever moves HA's own location (`homeassistant.set_location`, a geolocator integration), and your Apple "Home" follows the rig.

It doesn't decide *when* to update. You write the automation; this integration provides the action.

> **Does Find My follow it?** I haven't verified whether Find My's "Notify When Left Behind" home exception re-reads the contact card after it changes. Edit your card by hand once and check before you rely on it.

## Install

1. In HACS: ⋮ → **Custom repositories** → add `https://github.com/andrewcfitz/ha-icloud-home` as an **Integration**. Install **iCloud Home Address** and restart HA.
2. Create an **app-specific password** at [account.apple.com](https://account.apple.com) → Sign-In and Security → App-Specific Passwords.
3. **Settings → Devices & services → Add integration → iCloud Home Address**. Enter your Apple ID and the app-specific password, then pick your contact card from the list.

## Credentials

- You enter them once in the setup form. The password field is masked.
- Use an **app-specific password**, never your Apple ID password. It can't sign in to your Apple ID or change account settings, and you can revoke it at account.apple.com without touching anything else.
- HA stores them the way it stores every integration's credentials: in `/config/.storage/core.config_entries` on the HA host. That file is readable by anyone with file access to the box and isn't encrypted at rest. HA's automatic backups are encrypted.
- Credentials only go to `contacts.icloud.com` over HTTPS, as a Basic auth header. They're never put in URLs, never logged, and redacted from diagnostics.
- If Apple rejects the password (revoked, or the Apple ID password changed), the action fails and HA shows a **Re-authenticate** prompt for a new one.

## Action: `icloud_home.set_home_address`

Provide the address one of three ways. Explicit fields always win.

| Field | Use |
|---|---|
| `entity_id` | A Companion app **geocoded location** sensor (its address is used as-is), or a `device_tracker`/`person`/`zone` (its coordinates are reverse-geocoded) |
| `latitude` + `longitude` | Reverse-geocode these coordinates |
| `street`, `city`, `state`, `postal_code`, `country` | Set or override parts of the address |
| `dry_run` | Resolve and return the address without writing to iCloud |
| `config_entry_id` | Which account, only if you set up more than one |

Reverse geocoding uses [OpenStreetMap Nominatim](https://nominatim.org/), one request per call. Pass a geocoded sensor if you'd rather not send coordinates to a third party.

It refuses to write an address without a city and postal code, so a bad GPS fix can't blank your card. It writes only when the address changed (`changed: false` otherwise), and touches only the HOME address on the card.

Response:

```yaml
changed: true
dry_run: false
address: {street: 123 Campground Ln, city: Fredericksburg, state: TX, postal_code: "78624", country: United States}
```

## Example automation

Move HA's home and Apple's together once the rig is parked:

```yaml
automation:
  - alias: Home follows the RV
    triggers:
      - trigger: state
        entity_id: binary_sensor.shore_power
        to: "on"
        for: "00:10:00"
    actions:
      - action: homeassistant.set_location
        data:
          latitude: "{{ state_attr('device_tracker.iphone', 'latitude') }}"
          longitude: "{{ state_attr('device_tracker.iphone', 'longitude') }}"
      - action: icloud_home.set_home_address
        data:
          entity_id: sensor.iphone_geocoded_location
        response_variable: result
      - action: persistent_notification.create
        data:
          message: "Apple home: {{ result.address.street }}, {{ result.address.city }} (changed: {{ result.changed }})"
```

## Development

```sh
uv sync
uv run pytest
```

Tests run against a fake iCloud CardDAV account (redirect to a per-account host, address-book discovery, multiget, ETag-guarded PUT).

## License

MIT
