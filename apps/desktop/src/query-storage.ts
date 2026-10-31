export type QueryStorage = "auto" | "legacy" | "typed_sqlite";

// Change together with the core default after all release gates pass.
export const DEFAULT_QUERY_STORAGE: QueryStorage = "legacy";
