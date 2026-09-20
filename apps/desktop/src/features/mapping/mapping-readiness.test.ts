import { describe, expect, it } from "vitest";

import { deriveMappingReadiness } from "./mapping-readiness";
import type {
  MappingPayload,
  MappingValidation,
  MappingValidationIssue,
  StreamInfo
} from "../../types";

describe("deriveMappingReadiness", () => {
  it("returns ready for a valid mapping with enabled streams and no issues", () => {
    const readiness = deriveMappingReadiness({
      mapping: makeMapping(),
      streams: [makeStream()],
      validation: makeValidation()
    });

    expect(readiness.state).toBe("ready");
    expect(readiness.reasons).toEqual(["validation_clean"]);
    expect(readiness.enabledStreamCount).toBe(1);
  });

  it("returns review for a valid mapping with warning issues", () => {
    const readiness = deriveMappingReadiness({
      mapping: makeMapping(),
      validation: makeValidation({
        warnings: [makeIssue({ code: "field_nulls", severity: "warning" })]
      })
    });

    expect(readiness.state).toBe("review");
    expect(readiness.reasons).toContain("validation_warnings");
    expect(readiness.warningCount).toBe(1);
  });

  it("returns blocked when validation is invalid", () => {
    const readiness = deriveMappingReadiness({
      mapping: makeMapping(),
      validation: makeValidation({
        errors: [makeIssue({ code: "required_field_missing", severity: "error" })],
        valid: false
      })
    });

    expect(readiness.state).toBe("blocked");
    expect(readiness.reasons).toContain("validation_errors");
  });

  it("returns blocked when no streams are enabled", () => {
    const readiness = deriveMappingReadiness({
      mapping: makeMapping({ enabled: false }),
      validation: makeValidation()
    });

    expect(readiness.state).toBe("blocked");
    expect(readiness.reasons).toContain("no_enabled_streams");
  });

  it("returns blocked for unresolved ambiguous field matches", () => {
    const readiness = deriveMappingReadiness({
      mapping: makeMapping(),
      validation: makeValidation({
        errors: [makeIssue({ code: "ambiguous_field_match", severity: "error" })],
        valid: false
      })
    });

    expect(readiness.state).toBe("blocked");
    expect(readiness.reasons).toContain("unresolved_ambiguity");
  });

  it("treats ambiguous warning issues as unresolved ambiguity", () => {
    const readiness = deriveMappingReadiness({
      mapping: makeMapping(),
      validation: makeValidation({
        warnings: [makeIssue({ code: "ambiguous_time_match", severity: "warning" })]
      })
    });

    expect(readiness.state).toBe("blocked");
    expect(readiness.blockingIssues).toHaveLength(1);
  });

  it("does not downgrade valid low-confidence MCAP mappings", () => {
    const readiness = deriveMappingReadiness({
      mapping: makeMapping({ confidence: 0.42, semanticType: "mcap" }),
      streams: [makeStream({ confidence: 0.42, semantic_type: "mcap" })],
      validation: makeValidation()
    });

    expect(readiness.state).toBe("ready");
  });
});

function makeMapping(
  options: {
    confidence?: number;
    enabled?: boolean;
    semanticType?: string;
  } = {}
): MappingPayload {
  return {
    mapping: {
      schema_version: 2,
      id: "mapping_1",
      source: "source_1",
      app_id: "datascope.sensor_monitor.v1",
      recording_id: "recording_1",
      status: "draft",
      timelines: {
        primary: {
          name: "time",
          source_field: "time",
          unit: "auto",
          sort: "source"
        }
      },
      streams: [
        {
          stream_id: "stream_1",
          source_fields: ["temperature"],
          semantic_type: options.semanticType ?? "scalar",
          entity_path: "/temperature",
          archetype: "Scalar",
          view: "time_series",
          confidence: options.confidence ?? 0.91,
          enabled: options.enabled ?? true,
          required: false,
          origin: "inferred",
          rule_key: "inferred:stream_1"
        }
      ]
    }
  };
}

function makeValidation(
  options: {
    errors?: MappingValidationIssue[];
    valid?: boolean;
    warnings?: MappingValidationIssue[];
  } = {}
): MappingValidation {
  const errors = options.errors ?? [];
  const warnings = options.warnings ?? [];
  return {
    valid: options.valid ?? errors.length === 0,
    errors,
    warnings,
    issues: [...errors, ...warnings],
    summary: { errors: errors.length, warnings: warnings.length },
    effective_timeline_unit: "seconds"
  };
}

function makeIssue(overrides: Partial<MappingValidationIssue>): MappingValidationIssue {
  return {
    severity: "warning",
    code: "field_nulls",
    message: "Mapped fields contain empty values.",
    ...overrides
  };
}

function makeStream(overrides: Partial<StreamInfo> = {}): StreamInfo {
  return {
    stream_id: "stream_1",
    name: "temperature",
    semantic_type: "scalar",
    fields: ["temperature"],
    time_key: "time",
    confidence: 0.91,
    metadata: {},
    ...overrides
  };
}
