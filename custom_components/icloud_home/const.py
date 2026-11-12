"""Constants for the iCloud Home Address integration."""

DOMAIN = "icloud_home"

CONF_APPLE_ID = "apple_id"
CONF_APP_PASSWORD = "app_password"
CONF_CARD_URL = "card_url"
CONF_CARD_NAME = "card_name"

ICLOUD_ROOT = "https://contacts.icloud.com/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "ha-icloud-home/0.1.0"

ADDRESS_FIELDS = ("street", "city", "state", "postal_code", "country")

SERVICE_SET_HOME_ADDRESS = "set_home_address"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_DRY_RUN = "dry_run"
