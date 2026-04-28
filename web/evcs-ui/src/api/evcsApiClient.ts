import createClient from 'openapi-fetch';
import type { paths } from './schema';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export const apiClient = createClient<paths>({ baseUrl: BASE_URL });

type CreateSessionBody = NonNullable<
  paths['/api/v1/sessions']['post']['requestBody']
>['content']['application/json'];
type PatchSessionBody = NonNullable<
  paths['/api/v1/sessions/{session_id}']['patch']['requestBody']
>['content']['application/json'];
type SnapshotComputeBody = NonNullable<
  paths['/api/v1/snapshot/compute']['post']['requestBody']
>['content']['application/json'];
type TopologyPreviewBody = NonNullable<
  paths['/api/v1/topology/preview']['post']['requestBody']
>['content']['application/json'];
type ValidateCarPortsBody = NonNullable<
  paths['/api/v1/validate/car-ports']['post']['requestBody']
>['content']['application/json'];
type ValidateSystemConfigBody = NonNullable<
  paths['/api/v1/validate/system-config']['post']['requestBody']
>['content']['application/json'];

export const evcsApi = {
  getConstants: () => apiClient.GET('/api/v1/constants'),

  getPalette: (count: number, cycle: boolean) =>
    apiClient.GET('/api/v1/palette', {
      params: { query: { count, cycle } },
    }),

  validateModulePowers: (raw: string) =>
    apiClient.POST('/api/v1/validate/module-powers', { body: { raw } }),

  validateCarPorts: (body: ValidateCarPortsBody) =>
    apiClient.POST('/api/v1/validate/car-ports', { body }),

  validateSystemConfig: (cfg: ValidateSystemConfigBody) =>
    apiClient.POST('/api/v1/validate/system-config', { body: cfg }),

  createSession: (body: CreateSessionBody) =>
    apiClient.POST('/api/v1/sessions', { body }),

  patchSession: (sessionId: string, body: PatchSessionBody) =>
    apiClient.PATCH('/api/v1/sessions/{session_id}', {
      params: { path: { session_id: sessionId } },
      body,
    }),

  getSnapshot: (sessionId: string) =>
    apiClient.GET('/api/v1/sessions/{session_id}/snapshot', {
      params: { path: { session_id: sessionId } },
    }),

  computeSnapshot: (body: SnapshotComputeBody) =>
    apiClient.POST('/api/v1/snapshot/compute', { body }),

  topologyPreview: (body: TopologyPreviewBody) =>
    apiClient.POST('/api/v1/topology/preview', { body }),

  applyAndGenerate: (sessionId: string) =>
    apiClient.POST('/api/v1/sessions/{session_id}/apply-and-generate', {
      params: { path: { session_id: sessionId } },
    }),

  step: (sessionId: string, direction: 'forward' | 'back') =>
    apiClient.POST('/api/v1/sessions/{session_id}/step', {
      params: {
        path: { session_id: sessionId },
        query: { direction },
      },
    }),
};
