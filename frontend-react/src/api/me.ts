import apiClient from './client';

export interface MeResponse {
  principal_type: string;
  principal_id: string;
  display_name: string;
  email?: string | null;
  roles: string[];
  scopes: string[];
}

export async function getMe(): Promise<MeResponse> {
  const response = await apiClient.get<MeResponse>('/api/v1/me');
  return response.data;
}
