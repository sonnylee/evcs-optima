import { create } from 'zustand';
import { evcsApi } from '../api/evcsApiClient';
import type {
  CarPortInput,
  ControlStepSequence,
  ErrorDetail,
  Mode,
  NormalizedSnapshot,
  SystemConfig,
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

  // Player (FR-15) — Phase 3 will drive these
  mode: Mode;
  stepSequence: ControlStepSequence | null;
  currentStepIndex: number;

  // UX
  isLoading: boolean;
  globalError: string | null;

  // Actions (Phase 1 slice — config + topology only)
  initSession: (cfg: SystemConfig, ports?: CarPortInput[]) => Promise<void>;
  updateSystemConfig: (cfg: SystemConfig) => Promise<void>;
  refreshSnapshot: () => Promise<void>;
  clearConfigErrors: () => void;
}

const defaultPortsForCount = (recBdCount: number): CarPortInput[] =>
  Array.from({ length: recBdCount * 2 }, (_, i) => ({
    port_id: i + 1,
    max_required: 0,
    present: 0,
    target: 0,
    priority: null,
  }));

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
  isLoading: false,
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
      carPorts: data.car_ports,
      mode: data.mode,
      stepSequence: data.step_sequence ?? null,
      currentStepIndex: data.current_step_index,
      isLoading: false,
    });
    await get().refreshSnapshot();
  },

  updateSystemConfig: async (cfg) => {
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
      carPorts: data.car_ports,
      mode: data.mode,
      stepSequence: data.step_sequence ?? null,
      currentStepIndex: data.current_step_index,
      isLoading: false,
    });
    await get().refreshSnapshot();
  },

  refreshSnapshot: async () => {
    const sid = get().sessionId;
    if (!sid) return;
    const { data, error } = await evcsApi.getSnapshot(sid);
    if (error || !data) {
      set({ globalError: 'Failed to fetch snapshot' });
      return;
    }
    // Pydantic default_factory=list fields come through as optional in the
    // generated schema; normalize so components can rely on arrays existing.
    set({
      snapshot: {
        rec_bds: data.rec_bds ?? [],
        packs: data.packs ?? [],
        relays: data.relays ?? [],
        cars: data.cars ?? [],
        total_power_kw: data.total_power_kw ?? 0,
        total_requested_kw: data.total_requested_kw ?? 0,
        warnings: data.warnings ?? [],
      },
    });
  },

  clearConfigErrors: () => set({ configErrors: [] }),
}));
