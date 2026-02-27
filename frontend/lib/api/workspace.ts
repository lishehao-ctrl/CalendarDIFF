import { apiRequest } from "@/lib/api/client";
import { AppConfig, HealthResponse, WorkspaceBootstrapResponse } from "@/lib/types";

export function getWorkspaceBootstrap(config: AppConfig): Promise<WorkspaceBootstrapResponse> {
  return apiRequest<WorkspaceBootstrapResponse>(config, "/v1/workspace/bootstrap");
}

export function getHealth(config: AppConfig): Promise<HealthResponse> {
  return apiRequest<HealthResponse>(config, "/health");
}
