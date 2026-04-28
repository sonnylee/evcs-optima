// Fallbacks only — components should prefer the live values from the snapshot
// (RelaySnapshot.color, CarSnapshot.color, PackSnapshot.color) and the palette
// fetched from GET /api/v1/palette. These constants are kept as a safety net
// for unit tests / rendering before the palette has loaded.
export const FALLBACK_COLORS = {
  RELAY_CLOSED: '#E53E3E',
  RELAY_OPEN: '#FFFFFF',
  CAR_ACTIVE: '#3182CE',
  CAR_INACTIVE: '#A0AEC0',
  PACK_IDLE: '#EDF2F7',
} as const;
