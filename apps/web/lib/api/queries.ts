import { queryOptions } from "@tanstack/react-query";

import { api, unwrap } from "./client";

export const queryKeys = {
  me: ["me"] as const,
  demoUsers: ["demo-users"] as const,
  conversations: ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  manual: (docId: string) => ["manual", docId] as const,
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

export const manualQuery = (docId: string) =>
  queryOptions({
    queryKey: queryKeys.manual(docId),
    queryFn: () => unwrap(api.GET("/v1/manuals/{doc_id}", { params: { path: { doc_id: docId } } })),
    staleTime: Infinity,
    retry: false,
  });
