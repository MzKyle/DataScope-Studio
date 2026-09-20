import type {
  MappingPayload,
  MappingValidation,
  MappingValidationIssue,
  StreamInfo
} from "../../types";

export type MappingReadinessState = "ready" | "review" | "blocked";

export type MappingReadiness = {
  state: MappingReadinessState;
  reasons: string[];
  enabledStreamCount: number;
  detectedStreamCount: number;
  timelineField: string | null;
  blockingIssues: MappingValidationIssue[];
  reviewIssues: MappingValidationIssue[];
  errorCount: number;
  warningCount: number;
};

type DeriveMappingReadinessInput = {
  mapping: MappingPayload | null;
  streams?: StreamInfo[];
  validation: MappingValidation | null;
};

const AMBIGUITY_CODES = new Set(["ambiguous_field_match", "ambiguous_time_match"]);

export function deriveMappingReadiness({
  mapping,
  streams = [],
  validation
}: DeriveMappingReadinessInput): MappingReadiness {
  const mappingStreams = mapping?.mapping.streams ?? [];
  const enabledStreams = mappingStreams.filter((stream) => stream.enabled);
  const detectedStreamCount = streams.length || mappingStreams.length;
  const timelineField = mapping?.mapping.timelines.primary.source_field || null;
  const validationIssues = validation?.issues ?? [];
  const ambiguityIssues = validationIssues.filter((issue) => AMBIGUITY_CODES.has(issue.code));
  const blockingIssues = [
    ...(validation?.errors ?? []),
    ...ambiguityIssues.filter((issue) => issue.severity !== "error")
  ];
  const reviewIssues = (validation?.warnings ?? []).filter(
    (issue) => !AMBIGUITY_CODES.has(issue.code)
  );
  const reasons: string[] = [];

  if (!mapping) {
    return {
      state: "blocked",
      reasons: ["mapping_missing"],
      enabledStreamCount: 0,
      detectedStreamCount,
      timelineField,
      blockingIssues,
      reviewIssues,
      errorCount: validation?.summary.errors ?? 0,
      warningCount: validation?.summary.warnings ?? 0
    };
  }

  if (!enabledStreams.length) {
    reasons.push("no_enabled_streams");
  }

  if (!validation) {
    reasons.push("validation_pending");
  } else {
    if (!validation.valid || validation.errors.length > 0) {
      reasons.push("validation_errors");
    }
    if (ambiguityIssues.length > 0) {
      reasons.push("unresolved_ambiguity");
    }
    if (validation.warnings.length > 0) {
      reasons.push("validation_warnings");
    }
  }

  const blocked = reasons.some((reason) =>
    ["no_enabled_streams", "validation_errors", "unresolved_ambiguity"].includes(reason)
  );
  const review = reasons.some((reason) =>
    ["validation_pending", "validation_warnings"].includes(reason)
  );

  return {
    state: blocked ? "blocked" : review ? "review" : "ready",
    reasons: reasons.length ? reasons : ["validation_clean"],
    enabledStreamCount: enabledStreams.length,
    detectedStreamCount,
    timelineField,
    blockingIssues,
    reviewIssues,
    errorCount: validation?.summary.errors ?? 0,
    warningCount: validation?.summary.warnings ?? 0
  };
}
