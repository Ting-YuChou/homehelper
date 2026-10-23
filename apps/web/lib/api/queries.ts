import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";

import type { ReviewQuery } from "@/lib/admin/filters";

import { ApiError, api, unwrap } from "./client";

export const queryKeys = {
  me: ["me"] as const,
  demoUsers: ["demo-users"] as const,
  conversations: ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  manual: (docId: string) => ["manual", docId] as const,
  appliances: ["me", "appliances"] as const,
  attachment: (id: string) => ["attachment", id] as const,
  admin: ["admin"] as const,
  adminSession: ["admin", "session"] as const,
  adminConversations: (query: ReviewQuery) => ["admin", "conversations", query] as const,
  adminConversation: (id: string) => ["admin", "conversation", id] as const,
  adminAttachment: (id: string) => ["admin", "attachment", id] as const,
  adminManuals: ["admin", "manuals"] as const,
  adminEvals: ["admin", "evals"] as const,
  adminEval: (id: string) => ["admin", "evals", id] as const,
};

export const meQuery = queryOptions({
  queryKey: queryKeys.me,
  queryFn: () => unwrap(api.GET("/v1/auth/me")),
  retry: false,
});

export const demoUsersQuery = queryOptions({
  queryKey: queryKeys.demoUsers,
  queryFn: () => unwrap(api.GET("/v1/auth/demo-users")),
  staleTime: Infinity,
});

export const conversationsQuery = queryOptions({
  queryKey: queryKeys.conversations,
  queryFn: () => unwrap(api.GET("/v1/conversations")),
});

export const conversationQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.conversation(id),
    queryFn: () =>
      unwrap(
        api.GET("/v1/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
    retry: false,
  });

export const appliancesQuery = queryOptions({
  queryKey: queryKeys.appliances,
  queryFn: () => unwrap(api.GET("/v1/me/appliances")),
  retry: false, // show the error state at once instead of a long skeleton
});

export const manualQuery = (docId: string) =>
  queryOptions({
    queryKey: queryKeys.manual(docId),
    queryFn: () => unwrap(api.GET("/v1/manuals/{doc_id}", { params: { path: { doc_id: docId } } })),
    staleTime: Infinity,
    retry: false,
  });

// Signed URLs expire after 15 minutes (MEDIA_URL_TTL_S). A new URL would reload a playing video,
// so the URL is not refreshed in the background: a remount after 10 minutes gets a fresh one.
export const attachmentUrlQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.attachment(id),
    queryFn: () =>
      unwrap(
        api.GET("/v1/attachments/{attachment_id}", {
          params: { path: { attachment_id: id } },
        }),
      ),
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });

/** Whether this browser holds an admin session (the `hh_admin` cookie): true, or false on 401. */
export const adminSessionQuery = queryOptions({
  queryKey: queryKeys.adminSession,
  queryFn: async () => {
    try {
      await unwrap(api.GET("/v1/admin/session"));
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return false;
      throw error;
    }
  },
  retry: false,
});

export const adminConversationsQuery = (query: ReviewQuery) =>
  infiniteQueryOptions({
    queryKey: queryKeys.adminConversations(query),
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/v1/admin/conversations", {
          params: { query: { ...query, ...(pageParam ? { before: pageParam } : {}) } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_before,
    retry: false,
  });

export const adminConversationQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.adminConversation(id),
    queryFn: () =>
      unwrap(
        api.GET("/v1/admin/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
    retry: false,
  });

// Same freshness rules as `attachmentUrlQuery`.
export const adminAttachmentUrlQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.adminAttachment(id),
    queryFn: () =>
      unwrap(
        api.GET("/v1/admin/attachments/{attachment_id}", {
          params: { path: { attachment_id: id } },
        }),
      ),
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });

export const adminManualsQuery = queryOptions({
  queryKey: queryKeys.adminManuals,
  queryFn: () => unwrap(api.GET("/v1/admin/manuals")),
  staleTime: Infinity,
});

export const adminEvalsQuery = queryOptions({
  queryKey: queryKeys.adminEvals,
  queryFn: () => unwrap(api.GET("/v1/admin/evals")),
  retry: false,
});

export const adminEvalQuery = (id: string) =>
  queryOptions({
    queryKey: queryKeys.adminEval(id),
    queryFn: () =>
      unwrap(api.GET("/v1/admin/evals/{report_id}", { params: { path: { report_id: id } } })),
    retry: false,
  });
