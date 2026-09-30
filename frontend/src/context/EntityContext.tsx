"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/context/AuthContext";
import { clearPayrollResults } from "@/lib/payroll-session";
import {
  apiFetch,
  getActiveEntityId,
  parseEnvelopeResponse,
  setActiveEntityId,
} from "@/lib/api";

export type Entity = {
  id: string;
  org_id: string;
  name: string;
  legal_name: string | null;
  code: string;
  pf_establishment_code: string | null;
  esic_employer_code: string | null;
  tan: string | null;
  pan: string | null;
  cin: string | null;
  primary_state: string | null;
  is_active: boolean;
};

export type Organization = {
  id: string;
  name: string;
  org_type: "practice" | "enterprise";
};

type OrgContextPayload = {
  organization: Organization | null;
  role: string | null;
  active_role: string | null;
  entity_roles: Record<string, string>;
  can_manage_group: boolean;
  active_entity: Entity | null;
  entities: Entity[];
};

type EntityContextValue = {
  organization: Organization | null;
  role: string | null;
  activeRole: string | null;
  entityRoles: Record<string, string>;
  canManageGroup: boolean;
  entity: Entity | null;
  entities: Entity[];
  /** A practice has clients to switch between; an enterprise usually does not. */
  isMultiEntity: boolean;
  loading: boolean;
  switchEntity: (entityId: string) => Promise<void>;
  reload: () => Promise<void>;
  /**
   * Increments on every completed company switch. The shell keys the page on
   * it, so nothing a page held in memory — filters, selections, a half-typed
   * search — survives into the next company.
   */
  generation: number;
};

const EntityContext = createContext<EntityContextValue | undefined>(undefined);

export function EntityProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [payload, setPayload] = useState<OrgContextPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [generation, setGeneration] = useState(0);
  const queryClient = useQueryClient();

  const reload = useCallback(async () => {
    if (!isAuthenticated) {
      setPayload(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await apiFetch("/api/org/context");
      const data = await parseEnvelopeResponse<OrgContextPayload>(res);
      setPayload(data);
      // The server is the authority on which entity is active: the stored id
      // may name an entity this member can no longer reach.
      setActiveEntityId(data.active_entity?.id ?? null);
    } catch {
      setPayload(null);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const switchEntity = useCallback(
    async (entityId: string) => {
      // Set it locally first so the request that persists the choice is itself
      // made against the new entity, then reload everything downstream.
      const previous = getActiveEntityId();
      setActiveEntityId(entityId);
      let switched = false;
      try {
        const res = await apiFetch(`/api/org/entities/${entityId}/select`, { method: "POST" });
        await parseEnvelopeResponse(res);
        switched = previous !== entityId;
        if (switched) {
          clearPayrollResults();
          // Empty the cache rather than mark it stale: stale data stays on
          // screen, under the new company's name, until each refetch lands.
          queryClient.clear();
        }
      } catch (err) {
        setActiveEntityId(previous);
        throw err;
      } finally {
        await reload();
      }
      if (switched) {
        // Anything fetched while the reload was in flight may carry a key from
        // the old company; clear once more, then remount the page.
        queryClient.clear();
        setGeneration((g) => g + 1);
      }
    },
    [reload, queryClient],
  );

  const value = useMemo<EntityContextValue>(() => {
    const entities = payload?.entities ?? [];
    return {
      organization: payload?.organization ?? null,
      role: payload?.role ?? null,
      activeRole: payload?.active_role ?? null,
      entityRoles: payload?.entity_roles ?? {},
      canManageGroup: payload?.can_manage_group ?? false,
      entity: payload?.active_entity ?? null,
      entities,
      isMultiEntity: entities.length > 1 || payload?.organization?.org_type === "practice",
      loading,
      switchEntity,
      reload,
      generation,
    };
  }, [payload, loading, switchEntity, reload, generation]);

  return <EntityContext.Provider value={value}>{children}</EntityContext.Provider>;
}

export function useEntity(): EntityContextValue {
  const ctx = useContext(EntityContext);
  if (ctx === undefined) {
    throw new Error("useEntity must be used within an EntityProvider");
  }
  return ctx;
}

/** Reads the stored entity id without subscribing to the context. */
export { getActiveEntityId };
