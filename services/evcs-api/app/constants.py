"""System constants — single source of truth for FR-08/10/11/16 bounds."""

STEP_KW = 25                      # FR-08: 25 kW step
MAX_REQUIRED_MIN = 0              # FR-08: 0 kW lower bound
MAX_REQUIRED_MAX = 600            # FR-08: 600 kW upper bound
POWER_MIN_PER_MODULE = 50         # FR-11: single module min (kW)
POWER_MAX_PER_MODULE = 100        # FR-11: single module max (kW)
REC_BD_MIN = 1                    # FR-10: min REC BD count
REC_BD_MAX = 12                   # FR-10: max REC BD count
REC_BD_DEFAULT = 4                # FR-10: default REC BD count
CAR_PORTS_PER_REC_BD = 2          # FR-10: each REC BD → 2 Car Ports

DEFAULT_PALETTE_CYCLE = [
    "#3182CE",  # blue
    "#38A169",  # green
    "#DD6B20",  # orange
    "#805AD5",  # purple
]

EXTENDED_PALETTE = [
    "#3182CE", "#38A169", "#DD6B20", "#805AD5",
    "#D53F8C", "#319795", "#D69E2E", "#E53E3E",
    "#2C5282", "#276749", "#9C4221", "#553C9A",
]

RELAY_COLOR_CLOSED = "#E53E3E"    # FR-04: Closed = red
RELAY_COLOR_OPEN = "#FFFFFF"      # FR-04: Open = white
CAR_COLOR_ACTIVE = "#3182CE"      # FR-05: Active = blue
CAR_COLOR_INACTIVE = "#A0AEC0"    # FR-05: Inactive = light gray
PACK_COLOR_IDLE = "#EDF2F7"       # FR-03: idle pack
