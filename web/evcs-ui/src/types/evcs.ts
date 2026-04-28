import type { components } from '../api/schema';

// Normalized snapshot — the API has Pydantic default_factory=list fields, which
// OpenAPI schemagen marks as optional. The store coerces these to required
// arrays before exposing to components, so consumers don't need `?? []`.
export interface NormalizedSnapshot {
  rec_bds: components['schemas']['RecBdSnapshot'][];
  packs: components['schemas']['PackSnapshot'][];
  relays: components['schemas']['RelaySnapshot'][];
  cars: components['schemas']['CarSnapshot'][];
  total_power_kw: number;
  total_requested_kw: number;
  warnings: string[];
}

export type SystemConfig = components['schemas']['SystemConfig'];
export type RecBdConfig = components['schemas']['RecBdConfig'];
export type CarPortInput = components['schemas']['CarPortInput'];
export type VisualSnapshot = components['schemas']['VisualSnapshot'];
export type RecBdSnapshot = components['schemas']['RecBdSnapshot'];
export type PackSnapshot = components['schemas']['PackSnapshot'];
export type RelaySnapshot = components['schemas']['RelaySnapshot'];
export type CarSnapshot = components['schemas']['CarSnapshot'];
export type TopologyPreview = components['schemas']['TopologyPreview'];
export type RecBdView = components['schemas']['RecBdView'];
export type ControlStepSequence = components['schemas']['ControlStepSequence'];
export type ControlStep = components['schemas']['ControlStep'];
export type ErrorDetail = components['schemas']['ErrorDetail'];
export type WarningDetail = components['schemas']['WarningDetail'];
export type ModulePowerStringResponse =
  components['schemas']['ModulePowerStringResponse'];
export type SystemConfigValidateResponse =
  components['schemas']['SystemConfigValidateResponse'];
export type SessionState = components['schemas']['SessionState'];

export type Mode = 'edit' | 'player';
