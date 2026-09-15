"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { useAuth } from "@/context/AuthContext";
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
  active_entity: Entity | null;
  entities: Entity[];
};

type EntityContextValue = {
  organization: Organization | null;
  role: string | null;
  entity: Entity | null;
  entities: Entity[];
  /** A practice has clients to switch between; an enterprise usually does not. */
  isMultiEntity: boolean;
  loading: boolean;
  switchEntity: (entityId: string) => Promise<void>;
  reload: () => Promise<void>;
};

const EntityContext = createContext<EntityContextValue | undefined>(undefined);

export function EntityProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth();
  const [payload, setPayload] = useState<OrgContextPayload | null>(null);
  const [loading, setLoading] = useState(true);

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
      setActiveEntityId(entityId);
      try {
        await apiFetch(`/api/org/entities/${entityId}/select`, { method: "POST" });
      } finally {
        await reload();
      }
    },
    [reload],
  );

  const value = useMemo<EntityContextValue>(() => {
    const entities = payload?.entities ?? [];
    return {
      organization: payload?.organization ?? null,
      role: payload?.role ?? null,
      entity: payload?.active_entity ?? null,
      entities,
      isMultiEntity: entities.length > 1 || payload?.organization?.org_type === "practice",
      loading,
      switchEntity,
      reload,
    };
  }, [payload, loading, switchEntity, reload]);

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
