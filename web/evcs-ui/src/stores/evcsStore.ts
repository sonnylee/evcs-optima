import { create } from 'zustand';
import { evcsApi } from '../api/evcsApiClient';
import type {
  CarPortInput,
  ControlStepSequence,
  ErrorDetail,
  Mode,
  NormalizedSnapshot,
  SystemConfig,
  VisualSnapshot,
  WarningDetail,
} from '../types/evcs';

interface EvcsStore {
  // Identity
  sessionId: string | null;

  // Config (FR-10, FR-11)
  systemConfig: SystemConfig | null;
  configErrors: ErrorDetail[];

  // Car ports (FR-07, FR-12, FR-13, FR-16) — Phase 2 will populate these
  carPorts: CarPortInput[];
  carPortWarnings: WarningDetail[];
  carPortErrors: ErrorDetail[];

  // Snapshot (FR-02..06, FR-09) — store-normalized (no optional arrays).
  snapshot: NormalizedSnapshot | null;

  // Player (FR-14, FR-15)
  mode: Mode;
  stepSequence: ControlStepSequence | null;
  currentStepIndex: number;
  // Captured edit-mode snapshot so exitPlayer can restore without a server roundtrip.
  liveSnapshot: NormalizedSnapshot | null;

  // UX
  isLoading: boolean;
  isApplying: boolean;
  applyInfo: string | null;
  globalError: string | null;

  // Actions
  initSession: (cfg: SystemConfig, ports?: CarPortInput[]) => Promise<void>;
  updateSystemConfig: (cfg: SystemConfig) => Promise<void>;
  updateCarPort: (portId: number, patch: Partial<CarPortInput>) => Promise<void>;
  nudgeMaxRequired: (portId: number, delta: number) => Promise<void>;
  refreshSnapshot: () => Promise<void>;
  clearConfigErrors: () => void;
  applyAndGenerate: () => Promise<void>;
  stepForward: () => Promise<void>;
  stepBack: () => Promise<void>;
  exitPlayer: () => void;
}

const defaultPortsForCount = (recBdCount: number): CarPortInput[] =>
  Array.from({ length: recBdCount * 2 }, (_, i) => ({
    port_id: i + 1,
    max_required: 0,
    present: 0,
    target: 0,
    priority: null,
  }));

const normalizeSnapshot = (s: VisualSnapshot): NormalizedSnapshot => ({
  rec_bds: s.rec_bds ?? [],
  packs: s.packs ?? [],
  relays: s.relays ?? [],
  cars: s.cars ?? [],
  total_power_kw: s.total_power_kw ?? 0,
  total_requested_kw: s.total_requested_kw ?? 0,
  warnings: s.warnings ?? [],
});

export const useEvcsStore = create<EvcsStore>((set, get) => ({
  sessionId: null,
  systemConfig: null,
  configErrors: [],
  carPorts: [],
  carPortWarnings: [],
  carPortErrors: [],
  snapshot: null,
  mode: 'edit',
  stepSequence: null,
  currentStepIndex: 0,
  liveSnapshot: null,
  isLoading: false,
  isApplying: false,
  applyInfo: null,
  globalError: null,

  initSession: async (cfg, ports) => {
    set({ isLoading: true, globalError: null });
    const carPorts = ports ?? defaultPortsForCount(cfg.rec_bd_count);
    const { data, error } = await evcsApi.createSession({
      system_config: cfg,
      car_ports: carPorts,
    });
    if (error || !data) {
      set({ isLoading: false, globalError: 'Failed to create session' });
      return;
    }
    set({
      sessionId: data.session_id,
      systemConfig: data.system_config,
      carPorts: data.car_ports ?? [],
      mode: data.mode,
      stepSequence: data.step_sequence ?? null,
      currentStepIndex: data.current_step_index,
      isLoading: false,
    });
    await get().refreshSnapshot();
  },

  updateSystemConfig: async (cfg) => {
    if (get().mode === 'player') return;
    set({ isLoading: true, configErrors: [] });

    // 1. Validate config first
    const { data: vData, error: vError } = await evcsApi.validateSystemConfig(cfg);
    if (vError || !vData) {
      set({
        isLoading: false,
        globalError: 'Failed to validate config',
      });
      return;
    }
    if (vData.errors && vData.errors.length > 0) {
      set({ configErrors: vData.errors, isLoading: false });
      return;
    }

    // 2. If REC BD count changed, drop existing priority assignments (FR-16).
    const prev = get().systemConfig;
    let nextPorts = get().carPorts;
    if (!prev || prev.rec_bd_count !== cfg.rec_bd_count) {
      nextPorts = defaultPortsForCount(cfg.rec_bd_count);
    } else {
      nextPorts = nextPorts.map((p) => ({ ...p, priority: null }));
    }

    // 3. Either PATCH the existing session or create one if we don't have one yet.
    const sid = get().sessionId;
    if (!sid) {
      await get().initSession(cfg, nextPorts);
      return;
    }
    const { data, error } = await evcsApi.patchSession(sid, {
      system_config: cfg,
      car_ports: nextPorts,
    });
    if (error || !data) {
      set({ isLoading: false, globalError: 'Failed to update session config' });
      return;
    }
    set({
      systemConfig: data.system_config,
      carPorts: data.car_ports ?? [],
      mode: data.mode,
      stepSequence: data.step_sequence ?? null,
      currentStepIndex: data.current_step_index,
      isLoading: false,
    });
    await get().refreshSnapshot();
  },

  updateCarPort: async (portId, patch) => {
    if (get().mode === 'player') return;
    const sid = get().sessionId;
    if (!sid) return;

    // Snapshot prev state for rollback on PATCH failure.
    const prev = get().carPorts;

    // 1. Optimistic local update.
    const next = prev.map((p) =>
      p.port_id === portId ? { ...p, ...patch } : p,
    );
    set({ carPorts: next });

    // 2. PATCH backend with the full car_ports list (SPEC-WEB-API §1.2).
    const { data, error } = await evcsApi.patchSession(sid, { car_ports: next });
    if (error || !data) {
      // Rollback optimistic update — UI snaps back to last known-good state.
      set({
        carPorts: prev,
        globalError: 'Failed to update car port — try again',
      });
      return;
    }

    // 3. Replace local with server response to avoid drift.
    set({
      carPorts: data.car_ports ?? [],
      mode: data.mode,
      stepSequence: data.step_sequence ?? null,
      currentStepIndex: data.current_step_index,
    });

    // 4. Refresh snapshot ONLY when max_required changed (SPEC-WEB-UI §2.2).
    if ('max_required' in patch) {
      await get().refreshSnapshot();
    }
  },

  nudgeMaxRequired: async (portId, delta) => {
    if (get().mode === 'player') return;
    const port = get().carPorts.find((p) => p.port_id === portId);
    if (!port) return;
    const clamped = Math.max(0, Math.min(600, port.max_required + delta));
    if (clamped === port.max_required) return;
    await get().updateCarPort(portId, { max_required: clamped });
  },

  refreshSnapshot: async () => {
    const sid = get().sessionId;
    if (!sid) return;
    const { data, error } = await evcsApi.getSnapshot(sid);
    if (error || !data) {
      set({ globalError: 'Snapshot refresh failed — try the +/- button again' });
      return;
    }
    set({ snapshot: normalizeSnapshot(data) });
  },

  clearConfigErrors: () => set({ configErrors: [] }),

  applyAndGenerate: async () => {
    const sid = get().sessionId;
    if (!sid) return;

    set({ isApplying: true, applyInfo: null, globalError: null });

    const { data, error, response } = await evcsApi.applyAndGenerate(sid);

    if (error || !data) {
      const status = response?.status;
      let errMsg = 'Apply failed — try again';
      const detail = (error as { detail?: { errors?: ErrorDetail[] } } | undefined)
        ?.detail;
      if (status === 422 && detail?.errors?.length) {
        errMsg = detail.errors.map((e) => `${e.code}: ${e.message}`).join('; ');
      }
      set({ isApplying: false, globalError: errMsg });
      return;
    }

    // No-change short-circuit (SPEC-WEB-API §FR-14: Present == Target).
    if (data.total_steps === 0) {
      set({
        isApplying: false,
        applyInfo: 'No change required — system already at target state',
      });
      return;
    }

    // Capture current edit-mode snapshot so exitPlayer can restore without a roundtrip.
    const currentLive = get().snapshot;
    const playerSnapshot = normalizeSnapshot(data.initial_state);

    set({
      isApplying: false,
      mode: 'player',
      stepSequence: data,
      currentStepIndex: 0,
      snapshot: playerSnapshot,
      liveSnapshot: currentLive,
      applyInfo: null,
    });
  },

  stepForward: async () => {
    const sid = get().sessionId;
    if (!sid || get().mode !== 'player') return;
    const { data, error } = await evcsApi.step(sid, 'forward');
    if (error || !data) {
      set({ globalError: 'Step navigation failed' });
      return;
    }
    set({
      currentStepIndex: data.current_step_index,
      snapshot: normalizeSnapshot(data.snapshot),
    });
  },

  stepBack: async () => {
    const sid = get().sessionId;
    if (!sid || get().mode !== 'player') return;
    const { data, error } = await evcsApi.step(sid, 'back');
    if (error || !data) {
      set({ globalError: 'Step navigation failed' });
      return;
    }
    set({
      currentStepIndex: data.current_step_index,
      snapshot: normalizeSnapshot(data.snapshot),
    });
  },

  exitPlayer: () => {
    const live = get().liveSnapshot;
    set({
      mode: 'edit',
      currentStepIndex: 0,
      snapshot: live ?? get().snapshot,
      liveSnapshot: null,
    });
  },
}));
