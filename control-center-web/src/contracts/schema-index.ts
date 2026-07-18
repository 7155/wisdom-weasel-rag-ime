/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * The values are byte-stable projections of rag_ime/contracts/json/*.json.
 */

export const contractSchemas = {
  "active-rag-start.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.active-rag-start.v1",
    "type": "object",
    "properties": {
      "selectedText": {
        "type": "string"
      },
      "selected_text": {
        "type": "string"
      },
      "selectedTextHash": {
        "type": "string"
      },
      "selected_text_hash": {
        "type": "string"
      },
      "privacyDisposition": {
        "type": "string",
        "enum": [
          "allowed",
          "sensitive",
          "unknown"
        ]
      },
      "sensitiveField": {
        "type": "boolean"
      },
      "secureInput": {
        "type": "boolean"
      },
      "isPasswordField": {
        "type": "boolean"
      },
      "credentialField": {
        "type": "boolean"
      },
      "app": {
        "type": "string"
      },
      "frontAppBundleId": {
        "type": "string"
      },
      "windowContext": {
        "type": "object",
        "required": [
          "schemaVersion",
          "captureMode",
          "snapshotId",
          "revision",
          "application",
          "nodes"
        ],
        "properties": {
          "schemaVersion": {
            "const": "rag-ime.window-context.v1"
          },
          "captureMode": {
            "const": "accessibility_semantics"
          },
          "snapshotId": {
            "type": "string",
            "maxLength": 200
          },
          "revision": {
            "type": "integer",
            "minimum": 1
          },
          "capturedAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "privacyDisposition": {
            "type": "string",
            "enum": [
              "allowed",
              "sensitive",
              "unknown"
            ]
          },
          "application": {
            "type": "object",
            "properties": {
              "pid": {
                "type": "integer",
                "minimum": 0
              },
              "bundleId": {
                "type": "string",
                "maxLength": 300
              },
              "name": {
                "type": "string",
                "maxLength": 160
              },
              "windowTitle": {
                "type": "string",
                "maxLength": 240
              }
            },
            "additionalProperties": false
          },
          "focusedNodeRef": {
            "type": "string",
            "maxLength": 200
          },
          "nodes": {
            "type": "array",
            "maxItems": 160
          },
          "nodeCount": {
            "type": "integer",
            "minimum": 0,
            "maximum": 160
          },
          "truncated": {
            "type": "boolean"
          },
          "semanticText": {
            "type": "string",
            "maxLength": 12000
          }
        },
        "additionalProperties": false
      }
    },
    "additionalProperties": true
  },
  "active-rag-status.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.active-rag-status.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "sessionId",
      "status",
      "evidenceCount",
      "candidateCount",
      "diagnostics"
    ],
    "properties": {
      "schemaVersion": {
        "const": "rag-ime.active-rag-service.v1"
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "status": {
        "type": "string"
      },
      "evidenceCount": {
        "type": "integer",
        "minimum": 0
      },
      "candidateCount": {
        "type": "integer",
        "minimum": 0
      },
      "candidates": {
        "type": "array"
      },
      "stored": {
        "type": "boolean"
      },
      "noStore": {
        "type": "boolean"
      },
      "privacyAssessment": {
        "type": "object"
      },
      "storageReceipt": {
        "type": "object"
      },
      "diagnostics": {
        "type": "object",
        "required": [
          "contextInjection",
          "retrieval",
          "remoteModel"
        ],
        "properties": {
          "contextInjection": {
            "type": "object",
            "required": [
              "applied",
              "source",
              "contextChars",
              "contextHash",
              "selectedTextChars",
              "warnings"
            ],
            "properties": {
              "applied": {
                "type": "boolean"
              },
              "source": {
                "type": "string"
              },
              "contextChars": {
                "type": "integer",
                "minimum": 0
              },
              "contextHash": {
                "type": "string"
              },
              "selectedTextChars": {
                "type": "integer",
                "minimum": 0
              },
              "warnings": {
                "type": "array",
                "items": {
                  "type": "string"
                }
              }
            }
          },
          "retrieval": {
            "type": "object",
            "required": [
              "called",
              "evidenceCount",
              "lanes",
              "elapsedMs"
            ],
            "properties": {
              "called": {
                "type": "boolean"
              },
              "evidenceCount": {
                "type": "integer",
                "minimum": 0
              },
              "lanes": {
                "type": "object"
              },
              "elapsedMs": {
                "type": "number",
                "minimum": 0
              }
            }
          },
          "remoteModel": {
            "type": "object",
            "required": [
              "requested",
              "allowed",
              "provider",
              "model",
              "skipReason",
              "elapsedMs"
            ],
            "properties": {
              "requested": {
                "type": "boolean"
              },
              "allowed": {
                "type": "boolean"
              },
              "provider": {
                "type": "string"
              },
              "model": {
                "type": "string"
              },
              "skipReason": {
                "type": "string"
              },
              "elapsedMs": {
                "type": "number",
                "minimum": 0
              }
            }
          },
          "progress": {
            "type": "object",
            "required": [
              "stage",
              "elapsedMs",
              "context",
              "retrieval",
              "model"
            ],
            "properties": {
              "stage": {
                "type": "string"
              },
              "elapsedMs": {
                "type": "integer",
                "minimum": 0
              },
              "context": {
                "type": "object",
                "properties": {
                  "foregroundChars": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "windowNodeCount": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "windowCaptureMode": {
                    "type": "string"
                  },
                  "recentInputCount": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "recentInputChars": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "recentInputUsed": {
                    "type": "boolean"
                  }
                }
              },
              "retrieval": {
                "type": "object",
                "properties": {
                  "attempted": {
                    "type": "boolean"
                  },
                  "elapsedMs": {
                    "type": "number",
                    "minimum": 0
                  },
                  "retrievedCount": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "evidenceCount": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "contextEvidenceCount": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "items": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                      "type": "object",
                      "properties": {
                        "sourceType": {
                          "type": "string"
                        },
                        "sourceLane": {
                          "type": "string"
                        },
                        "title": {
                          "type": "string"
                        },
                        "preview": {
                          "type": "string"
                        }
                      }
                    }
                  }
                }
              },
              "model": {
                "type": "object",
                "properties": {
                  "attempted": {
                    "type": "boolean"
                  },
                  "partialVisible": {
                    "type": "boolean"
                  },
                  "partialChars": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "firstTokenMs": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "providerFirstTokenMs": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "providerElapsedMs": {
                    "type": "integer",
                    "minimum": 0
                  },
                  "qualityRetry": {
                    "type": "boolean"
                  },
                  "qualityRetryReason": {
                    "type": "string"
                  }
                }
              }
            }
          }
        }
      },
      "traceEvents": {
        "type": "array"
      }
    }
  },
  "activity-timeline-context.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.activity-timeline-context.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "available",
      "date",
      "timelineId",
      "status",
      "sourceEventHash",
      "summary",
      "segments",
      "eventCount",
      "retainedEventCount",
      "filteredInternalEventCount",
      "deduplicatedEventCount",
      "redactedEventCount",
      "corroborationOnly",
      "maySupportFacts"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.activity-timeline-context.v1"
      },
      "available": {
        "type": "boolean"
      },
      "date": {
        "type": "string",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "timelineId": {
        "type": "string"
      },
      "status": {
        "type": "string",
        "enum": [
          "unavailable",
          "draft",
          "approved"
        ]
      },
      "sourceEventHash": {
        "type": "string",
        "pattern": "^$|^[a-f0-9]{64}$"
      },
      "summary": {
        "type": "string",
        "maxLength": 2400
      },
      "segments": {
        "type": "array",
        "maxItems": 12,
        "items": {
          "$ref": "#/$defs/segment"
        }
      },
      "eventCount": {
        "type": "integer",
        "minimum": 0
      },
      "retainedEventCount": {
        "type": "integer",
        "minimum": 0
      },
      "filteredInternalEventCount": {
        "type": "integer",
        "minimum": 0
      },
      "deduplicatedEventCount": {
        "type": "integer",
        "minimum": 0
      },
      "redactedEventCount": {
        "type": "integer",
        "minimum": 0
      },
      "corroborationOnly": {
        "type": "boolean",
        "const": true
      },
      "maySupportFacts": {
        "type": "boolean",
        "const": false
      },
      "source": {
        "$ref": "#/$defs/source"
      },
      "ref": {
        "$ref": "#/$defs/ref"
      }
    },
    "$defs": {
      "segment": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "segmentId",
          "position",
          "app",
          "sourceKinds",
          "contextGroupIds",
          "startMs",
          "endMs",
          "eventCount",
          "summary",
          "redactedEventCount"
        ],
        "properties": {
          "segmentId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "position": {
            "type": "integer",
            "minimum": 0
          },
          "app": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "sourceKinds": {
            "type": "array",
            "maxItems": 12,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 120
            },
            "uniqueItems": true
          },
          "contextGroupIds": {
            "type": "array",
            "maxItems": 12,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 240
            },
            "uniqueItems": true
          },
          "startMs": {
            "type": "integer",
            "minimum": 0
          },
          "endMs": {
            "type": "integer",
            "minimum": 0
          },
          "eventCount": {
            "type": "integer",
            "minimum": 1
          },
          "summary": {
            "type": "string",
            "minLength": 1,
            "maxLength": 760
          },
          "redactedEventCount": {
            "type": "integer",
            "minimum": 0
          },
          "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "apps": {
            "type": "array",
            "maxItems": 12,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 240
            },
            "uniqueItems": true
          },
          "source": {
            "$ref": "#/$defs/source"
          },
          "ref": {
            "$ref": "#/$defs/ref"
          }
        }
      },
      "source": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "type",
          "id"
        ],
        "properties": {
          "type": {
            "type": "string",
            "const": "activity_timeline"
          },
          "id": {
            "type": "string",
            "minLength": 1
          }
        }
      },
      "ref": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "type",
          "id"
        ],
        "properties": {
          "type": {
            "type": "string",
            "const": "timeline"
          },
          "id": {
            "type": "string",
            "minLength": 1
          },
          "segmentId": {
            "type": "string",
            "minLength": 1
          }
        }
      }
    }
  },
  "agent-approval.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-approval.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "approvalId",
      "sessionId",
      "toolId",
      "operation",
      "payloadSha256",
      "preview",
      "riskLevel",
      "state",
      "requestedAtMs",
      "expiresAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-approval.v1"
      },
      "approvalId": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "toolId": {
        "type": "string",
        "minLength": 1
      },
      "operation": {
        "type": "string",
        "minLength": 1
      },
      "payloadSha256": {
        "type": "string",
        "minLength": 64
      },
      "preview": {
        "type": "object"
      },
      "riskLevel": {
        "type": "string",
        "enum": [
          "R1",
          "R2",
          "R3"
        ]
      },
      "state": {
        "type": "string",
        "enum": [
          "pending",
          "approved",
          "external_pending",
          "rejected",
          "expired",
          "stale",
          "applied",
          "failed"
        ]
      },
      "requestedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "expiresAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "decidedAtMs": {
        "type": [
          "integer",
          "null"
        ]
      },
      "receipt": {
        "type": [
          "object",
          "null"
        ]
      }
    }
  },
  "agent-artifact-inspection.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-artifact-inspection.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "artifact",
      "records",
      "totalRecords",
      "returnedRecords",
      "truncated",
      "limits"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-artifact-inspection.v1"
      },
      "artifact": {
        "type": "object"
      },
      "records": {
        "type": "array",
        "maxItems": 500,
        "items": {
          "type": "object"
        }
      },
      "totalRecords": {
        "type": "integer",
        "minimum": 0
      },
      "returnedRecords": {
        "type": "integer",
        "minimum": 0,
        "maximum": 500
      },
      "truncated": {
        "type": "boolean"
      },
      "limits": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "requestedRecords",
          "maxRecords",
          "maxOutputBytes"
        ],
        "properties": {
          "requestedRecords": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500
          },
          "maxRecords": {
            "type": "integer",
            "const": 500
          },
          "maxOutputBytes": {
            "type": "integer",
            "const": 262144
          }
        }
      }
    }
  },
  "agent-artifact-ref.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-artifact-ref.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "artifactId",
      "ownerKind",
      "ownerId",
      "kind",
      "mediaType",
      "appendOnly",
      "byteSize",
      "sha256",
      "recordCount",
      "snapshotRevision",
      "snapshotSha256",
      "createdAtMs",
      "updatedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-artifact-ref.v1"
      },
      "artifactId": {
        "type": "string",
        "minLength": 1
      },
      "ownerKind": {
        "type": "string",
        "enum": [
          "subagent_run",
          "tool_run",
          "connector_run"
        ]
      },
      "ownerId": {
        "type": "string",
        "minLength": 1
      },
      "kind": {
        "type": "string",
        "minLength": 1
      },
      "mediaType": {
        "type": "string",
        "minLength": 1
      },
      "appendOnly": {
        "type": "boolean"
      },
      "byteSize": {
        "type": "integer",
        "minimum": 0
      },
      "sha256": {
        "type": "string",
        "pattern": "^$|^[a-f0-9]{64}$"
      },
      "recordCount": {
        "type": "integer",
        "minimum": 0
      },
      "snapshotRevision": {
        "type": "integer",
        "minimum": 0
      },
      "snapshotSha256": {
        "type": "string",
        "pattern": "^$|^[a-f0-9]{64}$"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      }
    }
  },
  "agent-configuration.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-configuration.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "revision",
      "revisionToken",
      "configuration",
      "sync",
      "updatedAtMs",
      "updatedBy",
      "lastEventId"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-configuration.v1"
      },
      "revision": {
        "type": "integer",
        "minimum": 1
      },
      "revisionToken": {
        "type": "string",
        "minLength": 1
      },
      "configuration": {
        "type": "object",
        "required": [
          "runtime",
          "sessionDefaults",
          "coordination"
        ],
        "properties": {
          "runtime": {
            "type": "object",
            "required": [
              "enabled",
              "startup",
              "idleTimeoutSeconds"
            ],
            "properties": {
              "enabled": {
                "type": "boolean"
              },
              "startup": {
                "type": "string",
                "const": "lazy"
              },
              "idleTimeoutSeconds": {
                "type": "integer",
                "minimum": 0
              }
            }
          },
          "sessionDefaults": {
            "type": "object",
            "required": [
              "resumeLastSession",
              "roleId",
              "roleVersion",
              "modelProfile",
              "toolProfileVersion"
            ],
            "properties": {
              "resumeLastSession": {
                "type": "boolean"
              },
              "roleId": {
                "type": "string",
                "minLength": 1
              },
              "roleVersion": {
                "type": "string",
                "minLength": 1
              },
              "modelProfile": {
                "type": "string",
                "minLength": 1
              },
              "toolProfileVersion": {
                "type": "string",
                "minLength": 1
              }
            }
          },
          "coordination": {
            "type": "object",
            "required": [
              "enabled"
            ],
            "properties": {
              "enabled": {
                "type": "boolean"
              }
            }
          }
        }
      },
      "sync": {
        "type": "object",
        "required": [
          "state",
          "appliedRevision",
          "error"
        ],
        "properties": {
          "state": {
            "type": "string",
            "enum": [
              "synchronized",
              "pending",
              "failed"
            ]
          },
          "appliedRevision": {
            "type": "integer",
            "minimum": 0
          },
          "error": {
            "type": "string"
          }
        }
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedBy": {
        "type": "string",
        "minLength": 1
      },
      "lastEventId": {
        "type": "string"
      }
    }
  },
  "agent-context-item.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-context-item.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "itemId",
      "sessionId",
      "sourceKind",
      "sourceId",
      "lane",
      "lifecycle",
      "status",
      "title",
      "summary",
      "availableAtMs",
      "expiresAtMs",
      "deliveredTurnId",
      "createdAtMs",
      "updatedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-context-item.v1"
      },
      "itemId": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "sourceKind": {
        "type": "string",
        "minLength": 1
      },
      "sourceId": {
        "type": "string"
      },
      "lane": {
        "type": "string",
        "enum": [
          "result",
          "status",
          "notification",
          "room",
          "schedule",
          "fact"
        ]
      },
      "lifecycle": {
        "type": "string",
        "enum": [
          "once",
          "turn",
          "until_ack",
          "persistent"
        ]
      },
      "status": {
        "type": "string",
        "enum": [
          "pending",
          "delivered",
          "consumed",
          "acknowledged",
          "expired"
        ]
      },
      "title": {
        "type": "string",
        "minLength": 1
      },
      "summary": {
        "type": "string"
      },
      "availableAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "expiresAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      },
      "deliveredTurnId": {
        "type": "string"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      }
    }
  },
  "agent-context-trace.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-context-trace.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "traceId",
      "sessionId",
      "turnId",
      "sourceKind",
      "status",
      "finalFingerprint",
      "nodes",
      "edges",
      "createdAtMs",
      "updatedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-context-trace.v1"
      },
      "traceId": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "turnId": {
        "type": "string"
      },
      "sourceKind": {
        "type": "string",
        "minLength": 1
      },
      "status": {
        "type": "string",
        "enum": [
          "building",
          "accepted",
          "failed"
        ]
      },
      "finalFingerprint": {
        "type": "string",
        "pattern": "^$|^sha256:[a-f0-9]{16}$"
      },
      "nodes": {
        "type": "array",
        "maxItems": 64,
        "items": {
          "$ref": "#/$defs/node"
        }
      },
      "edges": {
        "type": "array",
        "maxItems": 128,
        "items": {
          "$ref": "#/$defs/edge"
        }
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      }
    },
    "$defs": {
      "node": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "nodeId",
          "ordinal",
          "stage",
          "label",
          "sourceKind",
          "disposition",
          "summary",
          "charCount",
          "tokenEstimate",
          "durationMs",
          "fingerprint",
          "reason",
          "metadata",
          "createdAtMs"
        ],
        "properties": {
          "nodeId": {
            "type": "string",
            "minLength": 1
          },
          "ordinal": {
            "type": "integer",
            "minimum": 1
          },
          "stage": {
            "type": "string",
            "minLength": 1
          },
          "label": {
            "type": "string",
            "minLength": 1
          },
          "sourceKind": {
            "type": "string",
            "minLength": 1
          },
          "disposition": {
            "type": "string",
            "enum": [
              "included",
              "omitted",
              "redacted",
              "failed"
            ]
          },
          "summary": {
            "type": "string"
          },
          "charCount": {
            "type": "integer",
            "minimum": 0
          },
          "tokenEstimate": {
            "type": "integer",
            "minimum": 0
          },
          "durationMs": {
            "type": "integer",
            "minimum": 0
          },
          "fingerprint": {
            "type": "string",
            "pattern": "^$|^sha256:[a-f0-9]{16}$"
          },
          "reason": {
            "type": "string"
          },
          "metadata": {
            "type": "object"
          },
          "createdAtMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "edge": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "source",
          "target"
        ],
        "properties": {
          "source": {
            "type": "string",
            "minLength": 1
          },
          "target": {
            "type": "string",
            "minLength": 1
          }
        }
      }
    }
  },
  "agent-control-bootstrap.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-control-bootstrap.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "apiVersion",
      "configuration",
      "runtime",
      "capabilities",
      "platform",
      "routes"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-control-bootstrap.v1"
      },
      "apiVersion": {
        "type": "string",
        "const": "control-api.v1"
      },
      "configuration": {
        "type": "object"
      },
      "runtime": {
        "type": "object"
      },
      "capabilities": {
        "type": "object",
        "required": [
          "schemaVersion",
          "items"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.control-capability-list.v1"
          },
          "items": {
            "type": "array"
          }
        }
      },
      "platform": {
        "type": "object"
      },
      "routes": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "pathId",
            "method",
            "remoteSafe",
            "subscription",
            "params",
            "query",
            "target"
          ],
          "properties": {
            "pathId": {
              "type": "string",
              "minLength": 1
            },
            "method": {
              "type": "string",
              "enum": [
                "GET",
                "POST",
                "PATCH",
                "DELETE"
              ]
            },
            "remoteSafe": {
              "type": "boolean"
            },
            "subscription": {
              "type": "boolean"
            },
            "params": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "query": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "remoteScopes": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "remoteQuery": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "target": {
              "type": "object",
              "required": [
                "8766",
                "8768"
              ],
              "properties": {
                "8766": {
                  "type": "string",
                  "minLength": 1
                },
                "8768": {
                  "type": [
                    "string",
                    "null"
                  ],
                  "minLength": 1
                }
              }
            }
          }
        }
      }
    }
  },
  "agent-control-event.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-control-event.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "eventId",
      "sequence",
      "eventType",
      "createdAtMs",
      "payload",
      "resumeToken"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-control-event.v1"
      },
      "eventId": {
        "type": "string",
        "minLength": 1
      },
      "sequence": {
        "type": "integer",
        "minimum": 0
      },
      "eventType": {
        "type": "string",
        "enum": [
          "configuration_changed",
          "configuration_applied",
          "configuration_failed",
          "snapshot_required"
        ]
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "payload": {
        "type": "object"
      },
      "resumeToken": {
        "type": "string"
      }
    }
  },
  "agent-conversation-context.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-conversation-context.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "available",
      "date",
      "messages",
      "messageCount",
      "deduplicatedMessageCount",
      "redactedMessageCount",
      "corroborationOnly",
      "maySupportFacts"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-conversation-context.v1"
      },
      "available": {
        "type": "boolean"
      },
      "date": {
        "type": "string",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "messages": {
        "type": "array",
        "maxItems": 24,
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "role",
            "sourceKind",
            "text",
            "occurredAtMs"
          ],
          "properties": {
            "role": {
              "type": "string",
              "enum": [
                "user",
                "assistant"
              ]
            },
            "sourceKind": {
              "type": "string",
              "enum": [
                "user_message",
                "assistant_message",
                "room_event"
              ]
            },
            "text": {
              "type": "string",
              "minLength": 1,
              "maxLength": 600
            },
            "occurredAtMs": {
              "type": "integer",
              "minimum": 0
            }
          }
        }
      },
      "messageCount": {
        "type": "integer",
        "minimum": 0
      },
      "deduplicatedMessageCount": {
        "type": "integer",
        "minimum": 0
      },
      "redactedMessageCount": {
        "type": "integer",
        "minimum": 0
      },
      "corroborationOnly": {
        "type": "boolean",
        "const": true
      },
      "maySupportFacts": {
        "type": "boolean",
        "const": false
      }
    }
  },
  "agent-event.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-event.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "eventId",
      "sessionId",
      "turnId",
      "sequence",
      "createdAtMs",
      "eventType",
      "payload",
      "resumeToken"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-event.v1"
      },
      "eventId": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "turnId": {
        "type": "string"
      },
      "sequence": {
        "type": "integer",
        "minimum": 1
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "eventType": {
        "type": "string",
        "enum": [
          "snapshot",
          "text_delta",
          "reasoning_summary",
          "status_changed",
          "session_configuration_changed",
          "message_queue_updated",
          "tool_started",
          "tool_progress",
          "tool_finished",
          "approval_required",
          "approval_resolved",
          "memory_checkpointed",
          "memory_maintenance_updated",
          "user_input_required",
          "message_completed",
          "compaction_started",
          "compaction_completed",
          "turn_completed",
          "turn_failed",
          "snapshot_required",
          "heartbeat"
        ]
      },
      "payload": {
        "type": "object"
      },
      "resumeToken": {
        "type": "string",
        "minLength": 1
      }
    }
  },
  "agent-media.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-media.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "mediaId",
      "sessionId",
      "mimeType",
      "byteSize",
      "sha256",
      "origin",
      "createdAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-media.v1"
      },
      "mediaId": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "fileName": {
        "type": "string",
        "maxLength": 160
      },
      "mimeType": {
        "type": "string",
        "enum": [
          "image/png",
          "image/jpeg",
          "image/gif",
          "image/webp",
          "audio/mpeg",
          "audio/mp4",
          "audio/wav",
          "application/pdf",
          "text/plain"
        ]
      },
      "byteSize": {
        "type": "integer",
        "minimum": 0
      },
      "sha256": {
        "type": "string",
        "minLength": 64
      },
      "width": {
        "type": [
          "integer",
          "null"
        ]
      },
      "height": {
        "type": [
          "integer",
          "null"
        ]
      },
      "durationMs": {
        "type": [
          "integer",
          "null"
        ]
      },
      "thumbnailMediaId": {
        "type": [
          "string",
          "null"
        ]
      },
      "origin": {
        "type": "string",
        "enum": [
          "user_attachment",
          "tool_result",
          "managed_asset"
        ]
      },
      "originTool": {
        "type": "string"
      },
      "originReceiptId": {
        "type": "string"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      }
    }
  },
  "agent-memory-evidence.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-memory-evidence.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "evidenceId",
      "project",
      "roleId",
      "sessionId",
      "sourceKind",
      "sourceId",
      "idempotencyKey",
      "text",
      "textSha256",
      "classification",
      "maySupportLongTermFact",
      "provenance",
      "metadata",
      "privacyClass",
      "status",
      "occurredAtMs",
      "recordedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-memory-evidence.v1"
      },
      "evidenceId": {
        "type": "string",
        "minLength": 1
      },
      "project": {
        "type": "string"
      },
      "roleId": {
        "type": "string"
      },
      "sessionId": {
        "type": "string"
      },
      "sourceKind": {
        "type": "string",
        "enum": [
          "user_message",
          "assistant_message",
          "tool_receipt",
          "session_digest",
          "room_event",
          "work_receipt"
        ]
      },
      "sourceId": {
        "type": "string",
        "minLength": 1
      },
      "idempotencyKey": {
        "type": "string",
        "minLength": 1
      },
      "text": {
        "type": "string",
        "minLength": 1
      },
      "textSha256": {
        "type": "string",
        "minLength": 64
      },
      "classification": {
        "type": "string",
        "const": "raw_evidence"
      },
      "maySupportLongTermFact": {
        "type": "boolean",
        "const": false
      },
      "provenance": {
        "type": "object"
      },
      "metadata": {
        "type": "object"
      },
      "privacyClass": {
        "type": "string",
        "enum": [
          "local",
          "private"
        ]
      },
      "status": {
        "type": "string",
        "enum": [
          "active",
          "tombstoned"
        ]
      },
      "occurredAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "recordedAtMs": {
        "type": "integer",
        "minimum": 0
      }
    }
  },
  "agent-memory-maintenance-status.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-memory-maintenance-status.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "ok",
      "policy",
      "autoApply",
      "scheduledDraftOnly",
      "due",
      "dueReason",
      "idleMs",
      "compileState",
      "pendingDraftCount",
      "runs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-memory-maintenance-status.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "policy": {
        "type": "string",
        "const": "review"
      },
      "autoApply": {
        "type": "boolean",
        "const": false
      },
      "scheduledDraftOnly": {
        "type": "boolean",
        "const": true
      },
      "due": {
        "type": "boolean"
      },
      "dueReason": {
        "type": "string",
        "enum": [
          "pending_events",
          "idle",
          "daily",
          "owner_daily",
          "draft_pending_review",
          "not_due"
        ]
      },
      "idleMs": {
        "type": "integer",
        "minimum": 0
      },
      "compileState": {
        "type": "object",
        "required": [
          "project",
          "lastCompiledEventId",
          "lastRunMs",
          "pendingEventCount",
          "lastBundleHash"
        ],
        "properties": {
          "project": {
            "type": "string"
          },
          "lastCompiledEventId": {
            "type": "integer",
            "minimum": 0
          },
          "lastRunMs": {
            "type": "integer",
            "minimum": 0
          },
          "pendingEventCount": {
            "type": "integer",
            "minimum": 0
          },
          "lastBundleHash": {
            "type": "string"
          }
        }
      },
      "pendingDraftCount": {
        "type": "integer",
        "minimum": 0
      },
      "ownerCuration": {
        "type": "object",
        "required": [
          "schemaVersion",
          "ok",
          "project",
          "policy",
          "due",
          "pendingSourceCount",
          "needsReviewSourceCount",
          "scopes"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.owner-memory-curation-status.v1"
          },
          "ok": {
            "type": "boolean",
            "const": true
          },
          "project": {
            "type": "string"
          },
          "policy": {
            "type": "object"
          },
          "due": {
            "type": "boolean"
          },
          "pendingSourceCount": {
            "type": "integer",
            "minimum": 0
          },
          "needsReviewSourceCount": {
            "type": "integer",
            "minimum": 0
          },
          "scopes": {
            "type": "array",
            "items": {
              "type": "object"
            }
          }
        }
      },
      "projection": {
        "type": "object",
        "required": [
          "schemaVersion",
          "ok",
          "configured",
          "owner",
          "running",
          "lastRunAtMs",
          "lastError",
          "freshness",
          "disabledReason"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.memory-projection-runtime.v1"
          },
          "ok": {
            "type": "boolean"
          },
          "configured": {
            "type": "boolean"
          },
          "owner": {
            "type": "string"
          },
          "running": {
            "type": "boolean"
          },
          "lastRunAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "lastError": {
            "type": "string"
          },
          "freshness": {
            "type": "object"
          },
          "disabledReason": {
            "type": "string"
          }
        }
      },
      "runs": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "runId",
            "createdAtMs",
            "status",
            "summary",
            "diffCount",
            "bundleHash",
            "sourceCursor",
            "ownerKind",
            "ownerId",
            "runKind"
          ],
          "properties": {
            "runId": {
              "type": "string",
              "minLength": 1
            },
            "createdAtMs": {
              "type": "integer",
              "minimum": 0
            },
            "status": {
              "type": "string",
              "enum": [
                "draft",
                "applied",
                "partial",
                "rolled_back",
                "superseded",
                "dismissed",
                "empty"
              ]
            },
            "summary": {
              "type": "string"
            },
            "diffCount": {
              "type": "integer",
              "minimum": 0
            },
            "bundleHash": {
              "type": "string"
            },
            "sourceCursor": {
              "type": "object"
            },
            "ownerKind": {
              "type": "string",
              "enum": [
                "user",
                "shared",
                "agent",
                "session",
                "room"
              ]
            },
            "ownerId": {
              "type": "string",
              "minLength": 1
            },
            "runKind": {
              "type": "string",
              "enum": [
                "legacy",
                "daily_curation",
                "manual_curation",
                "dream_insight"
              ]
            }
          }
        }
      }
    }
  },
  "agent-memory-source.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-memory-source.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "sourceId",
      "sessionId",
      "piEntryId",
      "inputEventId",
      "sourceRole",
      "sourceRevision",
      "canonicalTextSha256",
      "status",
      "ownerKind",
      "ownerId",
      "roleId",
      "roleVersion",
      "sourceKind",
      "trustClass",
      "disposition",
      "dispositionReason",
      "curationRunId",
      "coverageStartEntryId",
      "coverageEndEntryId",
      "metadata",
      "createdAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-memory-source.v1"
      },
      "sourceId": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "piEntryId": {
        "type": "string",
        "minLength": 1
      },
      "inputEventId": {
        "type": "integer",
        "minimum": 1
      },
      "sourceRole": {
        "type": "string",
        "enum": [
          "user",
          "tool_receipt"
        ]
      },
      "sourceRevision": {
        "type": "integer",
        "minimum": 1
      },
      "canonicalTextSha256": {
        "type": "string",
        "minLength": 64
      },
      "status": {
        "type": "string",
        "enum": [
          "active",
          "superseded",
          "archived",
          "tombstoned"
        ]
      },
      "ownerKind": {
        "type": "string",
        "enum": [
          "user",
          "shared",
          "agent",
          "session",
          "room"
        ]
      },
      "ownerId": {
        "type": "string",
        "minLength": 1
      },
      "roleId": {
        "type": "string"
      },
      "roleVersion": {
        "type": "string"
      },
      "sourceKind": {
        "type": "string",
        "enum": [
          "user_final",
          "tool_receipt",
          "session_compaction",
          "session_digest",
          "explicit_memory"
        ]
      },
      "trustClass": {
        "type": "string",
        "enum": [
          "user_claim",
          "applied_receipt",
          "session_summary",
          "assistant_claim",
          "explicit_command"
        ]
      },
      "disposition": {
        "type": "string",
        "enum": [
          "pending",
          "remember",
          "not_for_memory",
          "needs_review",
          "consolidated",
          "expired"
        ]
      },
      "dispositionReason": {
        "type": "string"
      },
      "dispositionUpdatedAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      },
      "processedAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      },
      "curationRunId": {
        "type": "string"
      },
      "coverageStartEntryId": {
        "type": "string"
      },
      "coverageEndEntryId": {
        "type": "string"
      },
      "expiresAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      },
      "metadata": {
        "type": "object"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "supersededAtMs": {
        "type": [
          "integer",
          "null"
        ]
      }
    }
  },
  "agent-message.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-message.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "id",
      "sessionId",
      "turnId",
      "role",
      "status",
      "blocks",
      "attachments",
      "citations",
      "createdAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-message.v1"
      },
      "id": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "turnId": {
        "type": "string"
      },
      "role": {
        "type": "string",
        "enum": [
          "user",
          "assistant",
          "tool",
          "system"
        ]
      },
      "status": {
        "type": "string",
        "enum": [
          "queued",
          "streaming",
          "completed",
          "failed",
          "aborted"
        ]
      },
      "blocks": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/block"
        }
      },
      "attachments": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "citations": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "completedAtMs": {
        "type": [
          "integer",
          "null"
        ]
      },
      "provider": {
        "type": "string"
      },
      "model": {
        "type": "string"
      },
      "usage": {
        "$ref": "#/$defs/usage"
      }
    },
    "$defs": {
      "usage": {
        "type": "object",
        "required": [
          "input",
          "output",
          "cacheRead",
          "cacheWrite",
          "totalTokens"
        ],
        "properties": {
          "input": {
            "type": "integer",
            "minimum": 0
          },
          "output": {
            "type": "integer",
            "minimum": 0
          },
          "cacheRead": {
            "type": "integer",
            "minimum": 0
          },
          "cacheWrite": {
            "type": "integer",
            "minimum": 0
          },
          "totalTokens": {
            "type": "integer",
            "minimum": 0
          }
        },
        "additionalProperties": false
      },
      "block": {
        "type": "object",
        "required": [
          "id",
          "type",
          "status",
          "presentationKind",
          "data"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1
          },
          "type": {
            "type": "string",
            "enum": [
              "text",
              "code",
              "reasoning_summary",
              "progress",
              "tool_call",
              "tool_result",
              "citation",
              "image",
              "audio",
              "file",
              "sticker",
              "task_plan",
              "diff",
              "approval",
              "error",
              "unknown"
            ]
          },
          "status": {
            "type": "string",
            "enum": [
              "queued",
              "running",
              "completed",
              "failed",
              "aborted"
            ]
          },
          "presentationKind": {
            "type": "string",
            "minLength": 1
          },
          "data": {
            "type": "object"
          }
        }
      }
    }
  },
  "agent-model-catalog.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-model-catalog.v1",
    "$defs": {
      "model": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "provider",
          "id",
          "name",
          "api",
          "reasoning",
          "thinkingLevels",
          "supportsImages",
          "contextWindow",
          "maxTokens"
        ],
        "properties": {
          "provider": {
            "type": "string",
            "minLength": 1
          },
          "id": {
            "type": "string",
            "minLength": 1
          },
          "name": {
            "type": "string",
            "minLength": 1
          },
          "api": {
            "type": "string"
          },
          "reasoning": {
            "type": "boolean"
          },
          "thinkingLevels": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "string",
              "enum": [
                "off",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max"
              ]
            }
          },
          "supportsImages": {
            "type": "boolean"
          },
          "contextWindow": {
            "type": "integer",
            "minimum": 0
          },
          "maxTokens": {
            "type": "integer",
            "minimum": 0
          }
        }
      }
    },
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "ok",
      "sessionId",
      "selected",
      "thinkingLevel",
      "providers"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-model-catalog.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "selected": {
        "type": [
          "object",
          "null"
        ]
      },
      "thinkingLevel": {
        "type": "string",
        "enum": [
          "off",
          "minimal",
          "low",
          "medium",
          "high",
          "xhigh",
          "max"
        ]
      },
      "providers": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "id",
            "displayName",
            "models"
          ],
          "properties": {
            "id": {
              "type": "string",
              "minLength": 1
            },
            "displayName": {
              "type": "string",
              "minLength": 1
            },
            "models": {
              "type": "array",
              "items": {
                "$ref": "#/$defs/model"
              }
            }
          }
        }
      }
    }
  },
  "agent-model-selection.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-model-selection.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "ok",
      "sessionId",
      "selected",
      "session"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-model-selection.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "selected": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "provider",
          "id",
          "name",
          "api",
          "reasoning",
          "thinkingLevels",
          "supportsImages",
          "contextWindow",
          "maxTokens"
        ],
        "properties": {
          "provider": {
            "type": "string",
            "minLength": 1
          },
          "id": {
            "type": "string",
            "minLength": 1
          },
          "name": {
            "type": "string",
            "minLength": 1
          },
          "api": {
            "type": "string"
          },
          "reasoning": {
            "type": "boolean"
          },
          "thinkingLevels": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "string",
              "enum": [
                "off",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max"
              ]
            }
          },
          "supportsImages": {
            "type": "boolean"
          },
          "contextWindow": {
            "type": "integer",
            "minimum": 0
          },
          "maxTokens": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "session": {
        "type": "object",
        "required": [
          "schemaVersion",
          "id",
          "modelProfile"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.agent-session.v1"
          },
          "id": {
            "type": "string",
            "minLength": 1
          },
          "modelProfile": {
            "type": "string",
            "minLength": 1
          }
        }
      }
    }
  },
  "agent-participant.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-participant.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "id",
      "roomId",
      "sessionId",
      "roleId",
      "roleVersion",
      "displayName",
      "collaborationRole",
      "status",
      "ordinal",
      "createdAtMs",
      "lastSpokeAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-participant.v1"
      },
      "id": {
        "type": "string",
        "minLength": 1
      },
      "roomId": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "roleId": {
        "type": "string",
        "minLength": 1
      },
      "roleVersion": {
        "type": "string",
        "minLength": 1
      },
      "displayName": {
        "type": "string",
        "minLength": 1,
        "maxLength": 40
      },
      "collaborationRole": {
        "type": "string",
        "enum": [
          "coordinator",
          "executor",
          "researcher"
        ]
      },
      "status": {
        "type": "string",
        "enum": [
          "active",
          "muted",
          "removed"
        ]
      },
      "ordinal": {
        "type": "integer",
        "minimum": 0,
        "maximum": 3
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "lastSpokeAtMs": {
        "type": [
          "integer",
          "null"
        ]
      }
    }
  },
  "agent-persona.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-persona.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "roleId",
      "version",
      "displayName",
      "tagline",
      "summary",
      "traits",
      "visualProfile",
      "defaults",
      "safetyPolicyVersion",
      "selectableModes"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-persona.v1"
      },
      "roleId": {
        "type": "string",
        "pattern": "^[a-z0-9][a-z0-9-]{1,62}$"
      },
      "version": {
        "type": "string",
        "pattern": "^[1-9][0-9]{0,5}$"
      },
      "displayName": {
        "type": "string",
        "minLength": 1,
        "maxLength": 40
      },
      "tagline": {
        "type": "string",
        "minLength": 1,
        "maxLength": 80
      },
      "summary": {
        "type": "string",
        "minLength": 1,
        "maxLength": 180
      },
      "traits": {
        "type": "array",
        "minItems": 1,
        "maxItems": 5,
        "uniqueItems": true,
        "items": {
          "type": "string",
          "minLength": 1,
          "maxLength": 24
        }
      },
      "visualProfile": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "avatarAssetId",
          "symbolName",
          "accentToken"
        ],
        "properties": {
          "avatarAssetId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80
          },
          "symbolName": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80
          },
          "accentToken": {
            "type": "string",
            "enum": [
              "teal",
              "blue",
              "rose",
              "neutral"
            ]
          }
        }
      },
      "defaults": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "modelPolicy",
          "memoryPolicy",
          "toolProfileVersion"
        ],
        "properties": {
          "modelPolicy": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80
          },
          "memoryPolicy": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80
          },
          "toolProfileVersion": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80
          },
          "modelProfile": {
            "type": "string",
            "pattern": "^[^/\\s]{1,80}/\\S{1,160}$"
          },
          "thinkingLevel": {
            "type": "string",
            "enum": [
              "off",
              "minimal",
              "low",
              "medium",
              "high",
              "xhigh",
              "max"
            ]
          }
        }
      },
      "safetyPolicyVersion": {
        "type": "string",
        "const": "control-center-safe-v1"
      },
      "selectableModes": {
        "type": "array",
        "minItems": 1,
        "maxItems": 2,
        "uniqueItems": true,
        "items": {
          "type": "string",
          "enum": [
            "assistant",
            "coordinator"
          ]
        }
      }
    }
  },
  "agent-role-book-tool-result.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-role-book-tool-result.v1",
    "title": "Agent Role Book Tool Result",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "operation",
      "roleId",
      "roleVersion",
      "summary",
      "activeRevisionChanged",
      "result"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-role-book-tool-result.v1"
      },
      "operation": {
        "type": "string",
        "enum": [
          "get",
          "history",
          "propose_revision",
          "review"
        ]
      },
      "roleId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 120
      },
      "roleVersion": {
        "type": "string",
        "minLength": 1,
        "maxLength": 80
      },
      "summary": {
        "type": "string",
        "minLength": 1,
        "maxLength": 400
      },
      "activeRevisionChanged": {
        "type": "boolean",
        "const": false
      },
      "result": {
        "type": "object"
      }
    }
  },
  "agent-role-book.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-role-book.v1",
    "title": "Agent Role Book Revision",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "revisionId",
      "roleId",
      "roleVersion",
      "revisionNumber",
      "status",
      "displayName",
      "mission",
      "basePersonaVersion",
      "sections",
      "sourceRevisionId",
      "changeSummary",
      "proposedBy",
      "createdAtMs",
      "activatedAtMs",
      "supersededAtMs",
      "rolledBackAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-role-book.v1"
      },
      "revisionId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240
      },
      "roleId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 120
      },
      "roleVersion": {
        "type": "string",
        "minLength": 1,
        "maxLength": 80
      },
      "revisionNumber": {
        "type": "integer",
        "minimum": 1
      },
      "status": {
        "type": "string",
        "enum": [
          "draft",
          "active",
          "superseded",
          "rolled_back"
        ]
      },
      "displayName": {
        "type": "string",
        "maxLength": 80
      },
      "mission": {
        "type": "string",
        "maxLength": 400
      },
      "basePersonaVersion": {
        "type": "string",
        "maxLength": 120
      },
      "sections": {
        "$ref": "#/$defs/sections"
      },
      "sourceRevisionId": {
        "type": "string",
        "maxLength": 240
      },
      "changeSummary": {
        "type": "string",
        "maxLength": 400
      },
      "proposedBy": {
        "type": "string",
        "maxLength": 120
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "activatedAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      },
      "supersededAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      },
      "rolledBackAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      }
    },
    "$defs": {
      "provenance": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "sourceType",
          "sourceId"
        ],
        "properties": {
          "sourceType": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80
          },
          "sourceId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "observedAtMs": {
            "type": [
              "integer",
              "null"
            ],
            "minimum": 0
          }
        }
      },
      "item": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "itemId",
          "text",
          "provenance",
          "evidenceIds"
        ],
        "properties": {
          "itemId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 280
          },
          "provenance": {
            "$ref": "#/$defs/provenance"
          },
          "expiresAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "evidenceIds": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 240
            }
          }
        }
      },
      "sections": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "personality",
          "capabilities",
          "recentWork",
          "lessonsAndLimits",
          "activeCommitments"
        ],
        "properties": {
          "personality": {
            "type": "array",
            "maxItems": 6,
            "items": {
              "$ref": "#/$defs/item"
            }
          },
          "capabilities": {
            "type": "array",
            "maxItems": 12,
            "items": {
              "$ref": "#/$defs/item"
            }
          },
          "recentWork": {
            "type": "array",
            "maxItems": 8,
            "items": {
              "$ref": "#/$defs/item"
            }
          },
          "lessonsAndLimits": {
            "type": "array",
            "maxItems": 8,
            "items": {
              "$ref": "#/$defs/item"
            }
          },
          "activeCommitments": {
            "type": "array",
            "maxItems": 8,
            "items": {
              "$ref": "#/$defs/item"
            }
          }
        }
      }
    }
  },
  "agent-role-routing-profile.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-role-routing-profile.v1",
    "title": "Agent Role Routing Profile",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "roleId",
      "roleVersion",
      "revisionId",
      "revisionNumber",
      "advisoryOnly",
      "personality",
      "capabilities",
      "recentWork",
      "activeCommitments",
      "lessonsAndLimits"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-role-routing-profile.v1"
      },
      "roleId": {
        "type": "string",
        "minLength": 1
      },
      "roleVersion": {
        "type": "string",
        "minLength": 1
      },
      "revisionId": {
        "type": "string",
        "minLength": 1
      },
      "revisionNumber": {
        "type": "integer",
        "minimum": 1
      },
      "advisoryOnly": {
        "type": "boolean"
      },
      "personality": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/routingItem"
        }
      },
      "capabilities": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/routingItem"
        }
      },
      "recentWork": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/routingItem"
        }
      },
      "activeCommitments": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/routingItem"
        }
      },
      "lessonsAndLimits": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/routingItem"
        }
      }
    },
    "$defs": {
      "routingItem": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "itemId",
          "text",
          "provenance",
          "evidenceIds"
        ],
        "properties": {
          "itemId": {
            "type": "string",
            "minLength": 1
          },
          "text": {
            "type": "string",
            "minLength": 1
          },
          "expiresAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "provenance": {
            "type": "object",
            "required": [
              "sourceType",
              "sourceId"
            ],
            "properties": {
              "sourceType": {
                "type": "string",
                "minLength": 1
              },
              "sourceId": {
                "type": "string",
                "minLength": 1
              },
              "observedAtMs": {
                "type": [
                  "integer",
                  "null"
                ],
                "minimum": 0
              }
            }
          },
          "evidenceIds": {
            "type": "array",
            "items": {
              "type": "string",
              "minLength": 1
            }
          }
        }
      }
    }
  },
  "agent-room-event.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-room-event.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "eventId",
      "roomId",
      "sequence",
      "turnId",
      "eventType",
      "participantId",
      "sourceSessionId",
      "createdAtMs",
      "payload",
      "resumeToken"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-room-event.v1"
      },
      "eventId": {
        "type": "string",
        "minLength": 1
      },
      "roomId": {
        "type": "string",
        "minLength": 1
      },
      "sequence": {
        "type": "integer",
        "minimum": 1
      },
      "turnId": {
        "type": "string"
      },
      "eventType": {
        "type": "string",
        "enum": [
          "user_message",
          "route_decision",
          "participant_status",
          "participant_delta",
          "participant_activity",
          "participant_message",
          "room_config_changed",
          "topic_changed",
          "artifact_changed",
          "turn_completed",
          "turn_failed",
          "snapshot_required"
        ]
      },
      "participantId": {
        "type": [
          "string",
          "null"
        ]
      },
      "sourceSessionId": {
        "type": "string"
      },
      "topicId": {
        "type": "string"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "payload": {
        "type": "object"
      },
      "resumeToken": {
        "type": "string",
        "minLength": 1
      }
    }
  },
  "agent-room-intercom.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-room-intercom.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "id",
      "roomId",
      "kind",
      "sourceParticipantId",
      "targetParticipantId",
      "sourceSessionId",
      "targetSessionId",
      "sourceGeneration",
      "targetGeneration",
      "clientMessageId",
      "replyTo",
      "workItemId",
      "workAction",
      "status",
      "content",
      "acceptedTurnId",
      "error",
      "createdAtMs",
      "updatedAtMs",
      "deliveredAtMs",
      "repliedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-room-intercom.v1"
      },
      "id": {
        "type": "string",
        "minLength": 1
      },
      "roomId": {
        "type": "string",
        "minLength": 1
      },
      "kind": {
        "type": "string",
        "enum": [
          "send",
          "ask",
          "reply"
        ]
      },
      "sourceParticipantId": {
        "type": "string",
        "minLength": 1
      },
      "targetParticipantId": {
        "type": "string",
        "minLength": 1
      },
      "sourceSessionId": {
        "type": "string",
        "minLength": 1
      },
      "targetSessionId": {
        "type": "string",
        "minLength": 1
      },
      "sourceGeneration": {
        "type": "integer",
        "minimum": 0
      },
      "targetGeneration": {
        "type": "integer",
        "minimum": 0
      },
      "clientMessageId": {
        "type": "string",
        "minLength": 1
      },
      "replyTo": {
        "type": "string"
      },
      "workItemId": {
        "type": "string"
      },
      "workAction": {
        "type": "string",
        "enum": [
          "",
          "assignment",
          "submission",
          "accepted",
          "revision",
          "blocked",
          "escalated"
        ]
      },
      "status": {
        "type": "string",
        "enum": [
          "queued",
          "delivering",
          "delivered",
          "replied",
          "failed",
          "stale",
          "cancelled"
        ]
      },
      "content": {
        "type": "string",
        "minLength": 1
      },
      "acceptedTurnId": {
        "type": "string"
      },
      "error": {
        "type": "string"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "deliveredAtMs": {
        "type": [
          "integer",
          "null"
        ]
      },
      "repliedAtMs": {
        "type": [
          "integer",
          "null"
        ]
      }
    }
  },
  "agent-room-snapshot.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-room-snapshot.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "ok",
      "room",
      "events",
      "firstSequence",
      "lastSequence",
      "resumeToken",
      "truncated"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-room-snapshot.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "room": {
        "$ref": "#/$defs/room"
      },
      "events": {
        "type": "array",
        "maxItems": 2000,
        "items": {
          "$ref": "#/$defs/event"
        }
      },
      "firstSequence": {
        "type": "integer",
        "minimum": 0
      },
      "lastSequence": {
        "type": "integer",
        "minimum": 0
      },
      "resumeToken": {
        "type": "string"
      },
      "truncated": {
        "type": "boolean"
      }
    },
    "$defs": {
      "participant": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "schemaVersion",
          "id",
          "roomId",
          "sessionId",
          "roleId",
          "roleVersion",
          "displayName",
          "collaborationRole",
          "status",
          "ordinal",
          "createdAtMs",
          "lastSpokeAtMs"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.agent-participant.v1"
          },
          "id": {
            "type": "string",
            "minLength": 1
          },
          "roomId": {
            "type": "string",
            "minLength": 1
          },
          "sessionId": {
            "type": "string",
            "minLength": 1
          },
          "roleId": {
            "type": "string",
            "minLength": 1
          },
          "roleVersion": {
            "type": "string",
            "minLength": 1
          },
          "displayName": {
            "type": "string",
            "minLength": 1,
            "maxLength": 40
          },
          "collaborationRole": {
            "type": "string",
            "enum": [
              "coordinator",
              "executor",
              "researcher"
            ]
          },
          "status": {
            "type": "string",
            "enum": [
              "active",
              "muted",
              "removed"
            ]
          },
          "ordinal": {
            "type": "integer",
            "minimum": 0,
            "maximum": 3
          },
          "createdAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "lastSpokeAtMs": {
            "type": [
              "integer",
              "null"
            ]
          }
        }
      },
      "room": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "schemaVersion",
          "id",
          "title",
          "status",
          "routingPolicy",
          "moderatorParticipantId",
          "workspaceRoots",
          "createdAtMs",
          "updatedAtMs",
          "lastEventSequence",
          "participants"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.agent-room.v1"
          },
          "id": {
            "type": "string",
            "minLength": 1
          },
          "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120
          },
          "status": {
            "type": "string",
            "enum": [
              "active",
              "archived"
            ]
          },
          "roomKind": {
            "type": "string",
            "enum": [
              "collaboration",
              "roleplay"
            ]
          },
          "avatar": {
            "type": "string",
            "maxLength": 80
          },
          "description": {
            "type": "string",
            "maxLength": 500
          },
          "scenarioPrompt": {
            "type": "string",
            "maxLength": 8000
          },
          "routingPolicy": {
            "type": "string",
            "enum": [
              "manual_mentions",
              "moderator",
              "sequential",
              "natural",
              "invite_only"
            ]
          },
          "routingConfig": {
            "type": "object"
          },
          "moderatorParticipantId": {
            "type": "string"
          },
          "nextSpeakerOrdinal": {
            "type": "integer",
            "minimum": 0,
            "maximum": 3
          },
          "activeTopicId": {
            "type": "string"
          },
          "configRevision": {
            "type": "integer",
            "minimum": 1
          },
          "workspaceRoots": {
            "type": "array",
            "maxItems": 4,
            "uniqueItems": true,
            "items": {
              "type": "string",
              "minLength": 1
            }
          },
          "createdAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "lastEventSequence": {
            "type": "integer",
            "minimum": 0
          },
          "participants": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {
              "$ref": "#/$defs/participant"
            }
          },
          "topics": {
            "type": "array",
            "maxItems": 200,
            "items": {
              "type": "object"
            }
          },
          "artifacts": {
            "type": "array",
            "maxItems": 100,
            "items": {
              "type": "object"
            }
          },
          "workItems": {
            "type": "array",
            "maxItems": 100,
            "items": {
              "type": "object"
            }
          }
        }
      },
      "event": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "schemaVersion",
          "eventId",
          "roomId",
          "sequence",
          "turnId",
          "eventType",
          "participantId",
          "sourceSessionId",
          "createdAtMs",
          "payload",
          "resumeToken"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.agent-room-event.v1"
          },
          "eventId": {
            "type": "string",
            "minLength": 1
          },
          "roomId": {
            "type": "string",
            "minLength": 1
          },
          "sequence": {
            "type": "integer",
            "minimum": 1
          },
          "turnId": {
            "type": "string"
          },
          "eventType": {
            "type": "string",
            "enum": [
              "user_message",
              "route_decision",
              "participant_status",
              "participant_delta",
              "participant_activity",
              "participant_message",
              "room_config_changed",
              "topic_changed",
              "artifact_changed",
              "turn_completed",
              "turn_failed",
              "snapshot_required"
            ]
          },
          "participantId": {
            "type": [
              "string",
              "null"
            ]
          },
          "sourceSessionId": {
            "type": "string"
          },
          "topicId": {
            "type": "string"
          },
          "createdAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "payload": {
            "type": "object"
          },
          "resumeToken": {
            "type": "string",
            "minLength": 1
          }
        }
      }
    }
  },
  "agent-room-work-item.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-room-work-item.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "id",
      "roomId",
      "topicId",
      "rootTurnId",
      "rootWorkId",
      "parentWorkId",
      "objective",
      "expectedOutput",
      "acceptanceCriteria",
      "accountableParticipantId",
      "currentOwnerParticipantId",
      "offeredToParticipantId",
      "createdByParticipantId",
      "clientMessageId",
      "state",
      "depth",
      "revision",
      "resultSummary",
      "artifactRefs",
      "evidenceRefs",
      "blocker",
      "acceptedTurnId",
      "createdAtMs",
      "updatedAtMs",
      "completedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-room-work-item.v1"
      },
      "id": {
        "type": "string",
        "minLength": 1
      },
      "roomId": {
        "type": "string",
        "minLength": 1
      },
      "topicId": {
        "type": "string"
      },
      "rootTurnId": {
        "type": "string"
      },
      "rootWorkId": {
        "type": "string",
        "minLength": 1
      },
      "parentWorkId": {
        "type": "string"
      },
      "objective": {
        "type": "string",
        "minLength": 1,
        "maxLength": 4000
      },
      "expectedOutput": {
        "type": "string",
        "minLength": 1,
        "maxLength": 2000
      },
      "acceptanceCriteria": {
        "type": "array",
        "minItems": 1,
        "maxItems": 8,
        "items": {
          "type": "string",
          "minLength": 1,
          "maxLength": 500
        }
      },
      "accountableParticipantId": {
        "type": "string",
        "minLength": 1
      },
      "currentOwnerParticipantId": {
        "type": "string",
        "minLength": 1
      },
      "offeredToParticipantId": {
        "type": "string"
      },
      "createdByParticipantId": {
        "type": "string",
        "minLength": 1
      },
      "clientMessageId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 200
      },
      "state": {
        "type": "string",
        "enum": [
          "queued",
          "active",
          "review",
          "blocked",
          "done",
          "failed",
          "cancelled"
        ]
      },
      "depth": {
        "type": "integer",
        "minimum": 1,
        "maximum": 3
      },
      "revision": {
        "type": "integer",
        "minimum": 0,
        "maximum": 2
      },
      "resultSummary": {
        "type": "string",
        "maxLength": 4000
      },
      "artifactRefs": {
        "type": "array",
        "maxItems": 16,
        "items": {
          "type": "string",
          "minLength": 1,
          "maxLength": 1000
        }
      },
      "evidenceRefs": {
        "type": "array",
        "maxItems": 24,
        "items": {
          "type": "string",
          "minLength": 1,
          "maxLength": 1000
        }
      },
      "blocker": {
        "type": "object"
      },
      "acceptedTurnId": {
        "type": "string"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "completedAtMs": {
        "type": [
          "integer",
          "null"
        ]
      }
    }
  },
  "agent-room.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-room.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "id",
      "title",
      "status",
      "routingPolicy",
      "moderatorParticipantId",
      "workspaceRoots",
      "createdAtMs",
      "updatedAtMs",
      "lastEventSequence",
      "participants"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-room.v1"
      },
      "id": {
        "type": "string",
        "minLength": 1
      },
      "title": {
        "type": "string",
        "minLength": 1,
        "maxLength": 120
      },
      "status": {
        "type": "string",
        "enum": [
          "active",
          "archived"
        ]
      },
      "roomKind": {
        "type": "string",
        "enum": [
          "collaboration",
          "roleplay"
        ]
      },
      "avatar": {
        "type": "string",
        "maxLength": 80
      },
      "description": {
        "type": "string",
        "maxLength": 500
      },
      "scenarioPrompt": {
        "type": "string",
        "maxLength": 8000
      },
      "routingPolicy": {
        "type": "string",
        "enum": [
          "manual_mentions",
          "moderator",
          "sequential",
          "natural",
          "invite_only"
        ]
      },
      "routingConfig": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "maxResponders",
          "naturalJitter",
          "fallbackParticipantId"
        ],
        "properties": {
          "maxResponders": {
            "type": "integer",
            "const": 1
          },
          "naturalJitter": {
            "type": "number",
            "minimum": 0,
            "maximum": 0.15
          },
          "fallbackParticipantId": {
            "type": "string"
          }
        }
      },
      "moderatorParticipantId": {
        "type": "string"
      },
      "nextSpeakerOrdinal": {
        "type": "integer",
        "minimum": 0,
        "maximum": 3
      },
      "activeTopicId": {
        "type": "string"
      },
      "configRevision": {
        "type": "integer",
        "minimum": 1
      },
      "workspaceRoots": {
        "type": "array",
        "maxItems": 4,
        "uniqueItems": true,
        "items": {
          "type": "string",
          "minLength": 1
        }
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "lastEventSequence": {
        "type": "integer",
        "minimum": 0
      },
      "participants": {
        "type": "array",
        "minItems": 2,
        "maxItems": 4,
        "items": {
          "type": "object"
        }
      },
      "topics": {
        "type": "array",
        "maxItems": 200,
        "items": {
          "type": "object"
        }
      },
      "artifacts": {
        "type": "array",
        "maxItems": 100,
        "items": {
          "type": "object"
        }
      },
      "workItems": {
        "type": "array",
        "maxItems": 100,
        "items": {
          "type": "object"
        }
      }
    }
  },
  "agent-runtime-binding.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-runtime-binding.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "driverId",
      "runtimeKind",
      "generation",
      "state",
      "createdAtMs",
      "updatedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-runtime-binding.v1"
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "driverId": {
        "type": "string",
        "minLength": 1
      },
      "runtimeKind": {
        "type": "string",
        "minLength": 1
      },
      "externalSessionId": {
        "type": "string",
        "minLength": 1
      },
      "transcriptRef": {
        "type": "string"
      },
      "branchAnchor": {
        "type": "string"
      },
      "generation": {
        "type": "integer",
        "minimum": 1
      },
      "state": {
        "type": "string",
        "enum": [
          "prepared",
          "active",
          "stale"
        ]
      },
      "metadata": {
        "type": "object"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      }
    }
  },
  "agent-runtime.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-runtime.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "enabled",
      "managed",
      "status",
      "piVersion",
      "idleTimeoutSeconds",
      "capabilities"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-runtime.v1"
      },
      "enabled": {
        "type": "boolean"
      },
      "managed": {
        "type": "boolean"
      },
      "status": {
        "type": "string",
        "enum": [
          "disabled",
          "not_installed",
          "needs_configuration",
          "stopped",
          "starting",
          "ready",
          "busy",
          "faulted"
        ]
      },
      "driverId": {
        "type": "string",
        "minLength": 1
      },
      "runtimeKind": {
        "type": "string",
        "minLength": 1
      },
      "runtimeVersion": {
        "type": "string"
      },
      "piVersion": {
        "type": "string"
      },
      "idleTimeoutSeconds": {
        "type": "integer",
        "minimum": 0
      },
      "activeSessionId": {
        "type": [
          "string",
          "null"
        ]
      },
      "lastError": {
        "type": "string"
      },
      "capabilities": {
        "type": "object"
      }
    }
  },
  "agent-session-fork-candidates.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-session-fork-candidates.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "ok",
      "sessionId",
      "items"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-session-fork-candidates.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "items": {
        "type": "array",
        "maxItems": 500,
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "entryId",
            "text",
            "role",
            "createdAtMs"
          ],
          "properties": {
            "entryId": {
              "type": "string",
              "minLength": 1,
              "maxLength": 240
            },
            "text": {
              "type": "string",
              "minLength": 1,
              "maxLength": 8000
            },
            "role": {
              "type": "string",
              "enum": [
                "user",
                "assistant"
              ]
            },
            "createdAtMs": {
              "type": "integer",
              "minimum": 0
            }
          }
        }
      }
    }
  },
  "agent-session-fork-create.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-session-fork-create.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "ok",
      "sourceSessionId",
      "entryId",
      "selectedText",
      "session"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-session-fork-create.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "sourceSessionId": {
        "type": "string",
        "minLength": 1
      },
      "entryId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240
      },
      "selectedText": {
        "type": "string",
        "maxLength": 8000
      },
      "session": {
        "$ref": "#/$defs/session"
      }
    },
    "$defs": {
      "session": {
        "type": "object",
        "required": [
          "schemaVersion",
          "id",
          "title",
          "mode",
          "status",
          "roleId",
          "roleVersion",
          "roleBookRevisionId",
          "modelProfile",
          "toolProfileVersion",
          "projectContextEnabled",
          "piSkillsEnabled",
          "codexSkillsEnabled",
          "createdAtMs",
          "updatedAtMs",
          "messageCount",
          "workspaceRoots"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.agent-session.v1"
          },
          "id": {
            "type": "string",
            "minLength": 1
          },
          "title": {
            "type": "string",
            "minLength": 1
          },
          "mode": {
            "type": "string",
            "enum": [
              "assistant",
              "coordinator"
            ]
          },
          "status": {
            "type": "string",
            "enum": [
              "idle",
              "active",
              "busy",
              "faulted",
              "archived"
            ]
          },
          "roleId": {
            "type": "string",
            "minLength": 1
          },
          "roleVersion": {
            "type": "string",
            "minLength": 1
          },
          "roleBookRevisionId": {
            "type": "string",
            "maxLength": 240
          },
          "modelProfile": {
            "type": "string",
            "minLength": 1
          },
          "toolProfileVersion": {
            "type": "string",
            "minLength": 1
          },
          "projectContextEnabled": {
            "type": "boolean"
          },
          "piSkillsEnabled": {
            "type": "boolean"
          },
          "codexSkillsEnabled": {
            "type": "boolean"
          },
          "createdAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "messageCount": {
            "type": "integer",
            "minimum": 0
          },
          "workspaceRoots": {
            "type": "array",
            "items": {
              "type": "string"
            }
          }
        }
      }
    }
  },
  "agent-session-telemetry.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-session-telemetry.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "model",
      "context",
      "cumulativeUsage",
      "latestUsage",
      "latestCacheHitPercent",
      "isCompacting",
      "compactionCount",
      "updatedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-session-telemetry.v1"
      },
      "model": {
        "type": "object",
        "required": [
          "provider",
          "id",
          "name"
        ],
        "properties": {
          "provider": {
            "type": "string"
          },
          "id": {
            "type": "string"
          },
          "name": {
            "type": "string"
          }
        },
        "additionalProperties": true
      },
      "context": {
        "type": "object",
        "required": [
          "tokens",
          "contextWindow",
          "percent",
          "remainingTokens",
          "compactAtTokens",
          "tokensUntilCompact",
          "reserveTokens",
          "keepRecentTokens",
          "autoCompactEnabled"
        ],
        "properties": {
          "tokens": {
            "type": [
              "integer",
              "null"
            ],
            "minimum": 0
          },
          "contextWindow": {
            "type": "integer",
            "minimum": 0
          },
          "percent": {
            "type": [
              "number",
              "null"
            ],
            "minimum": 0
          },
          "remainingTokens": {
            "type": [
              "integer",
              "null"
            ],
            "minimum": 0
          },
          "compactAtTokens": {
            "type": "integer",
            "minimum": 0
          },
          "tokensUntilCompact": {
            "type": [
              "integer",
              "null"
            ],
            "minimum": 0
          },
          "reserveTokens": {
            "type": "integer",
            "minimum": 0
          },
          "keepRecentTokens": {
            "type": "integer",
            "minimum": 0
          },
          "autoCompactEnabled": {
            "type": "boolean"
          }
        },
        "additionalProperties": false
      },
      "cumulativeUsage": {
        "$ref": "#/$defs/usage"
      },
      "latestUsage": {
        "$ref": "#/$defs/usage"
      },
      "latestCacheHitPercent": {
        "type": [
          "number",
          "null"
        ],
        "minimum": 0,
        "maximum": 100
      },
      "isCompacting": {
        "type": "boolean"
      },
      "compactionCount": {
        "type": "integer",
        "minimum": 0
      },
      "latestCompaction": {
        "type": "object",
        "required": [
          "reason",
          "status",
          "updatedAtMs"
        ],
        "properties": {
          "reason": {
            "type": "string",
            "enum": [
              "manual",
              "threshold",
              "overflow"
            ]
          },
          "status": {
            "type": "string",
            "enum": [
              "running",
              "completed",
              "failed",
              "aborted"
            ]
          },
          "tokensBefore": {
            "type": "integer",
            "minimum": 0
          },
          "estimatedTokensAfter": {
            "type": "integer",
            "minimum": 0
          },
          "willRetry": {
            "type": "boolean"
          },
          "error": {
            "type": "string"
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          }
        },
        "additionalProperties": false
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      }
    },
    "$defs": {
      "usage": {
        "type": "object",
        "required": [
          "input",
          "output",
          "cacheRead",
          "cacheWrite",
          "totalTokens"
        ],
        "properties": {
          "input": {
            "type": "integer",
            "minimum": 0
          },
          "output": {
            "type": "integer",
            "minimum": 0
          },
          "cacheRead": {
            "type": "integer",
            "minimum": 0
          },
          "cacheWrite": {
            "type": "integer",
            "minimum": 0
          },
          "totalTokens": {
            "type": "integer",
            "minimum": 0
          }
        },
        "additionalProperties": false
      }
    },
    "additionalProperties": false
  },
  "agent-session.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-session.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "id",
      "title",
      "mode",
      "status",
      "roleId",
      "roleVersion",
      "roleBookRevisionId",
      "modelProfile",
      "toolProfileVersion",
      "projectContextEnabled",
      "piSkillsEnabled",
      "codexSkillsEnabled",
      "createdAtMs",
      "updatedAtMs",
      "messageCount",
      "workspaceRoots"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-session.v1"
      },
      "id": {
        "type": "string",
        "minLength": 1
      },
      "piSessionId": {
        "type": "string"
      },
      "sessionFile": {
        "type": "string"
      },
      "runtimeBinding": {
        "type": "object",
        "required": [
          "schemaVersion",
          "driverId",
          "runtimeKind",
          "generation",
          "state",
          "createdAtMs",
          "updatedAtMs"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.agent-runtime-binding.v1"
          },
          "driverId": {
            "type": "string",
            "minLength": 1
          },
          "runtimeKind": {
            "type": "string",
            "minLength": 1
          },
          "generation": {
            "type": "integer",
            "minimum": 1
          },
          "state": {
            "type": "string",
            "enum": [
              "prepared",
              "active",
              "stale"
            ]
          },
          "createdAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "title": {
        "type": "string",
        "minLength": 1
      },
      "mode": {
        "type": "string",
        "enum": [
          "assistant",
          "coordinator"
        ]
      },
      "status": {
        "type": "string",
        "enum": [
          "idle",
          "active",
          "busy",
          "faulted",
          "archived"
        ]
      },
      "sessionKind": {
        "type": "string",
        "enum": [
          "conversation",
          "subagent_runtime"
        ]
      },
      "roleId": {
        "type": "string",
        "minLength": 1
      },
      "roleVersion": {
        "type": "string",
        "minLength": 1
      },
      "roleBookRevisionId": {
        "type": "string",
        "maxLength": 240
      },
      "modelProfile": {
        "type": "string",
        "minLength": 1
      },
      "thinkingLevel": {
        "type": "string",
        "enum": [
          "",
          "off",
          "minimal",
          "low",
          "medium",
          "high",
          "xhigh",
          "max"
        ]
      },
      "toolProfileVersion": {
        "type": "string",
        "minLength": 1
      },
      "toolAllowlistMode": {
        "type": "string",
        "enum": [
          "profile",
          "explicit"
        ]
      },
      "allowedTools": {
        "type": "array",
        "items": {
          "type": "string",
          "minLength": 1
        },
        "uniqueItems": true
      },
      "projectContextEnabled": {
        "type": "boolean"
      },
      "piSkillsEnabled": {
        "type": "boolean"
      },
      "codexSkillsEnabled": {
        "type": "boolean"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "lastOpenedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "archivedAtMs": {
        "type": [
          "integer",
          "null"
        ]
      },
      "messageCount": {
        "type": "integer",
        "minimum": 0
      },
      "lastMessagePreview": {
        "type": "string"
      },
      "workspaceRoots": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "shellPolicyVersion": {
        "type": "string"
      }
    }
  },
  "agent-subagent-batch.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-subagent-batch.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "id",
      "parentSessionId",
      "parentRunId",
      "contextMode",
      "state",
      "depth",
      "maxDepth",
      "abortRequested",
      "createdAtMs",
      "updatedAtMs",
      "completedAtMs",
      "runs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-subagent-batch.v1"
      },
      "id": {
        "type": "string",
        "minLength": 1
      },
      "parentSessionId": {
        "type": "string",
        "minLength": 1
      },
      "parentRunId": {
        "type": "string"
      },
      "contextMode": {
        "type": "string",
        "enum": [
          "fresh",
          "fork"
        ]
      },
      "state": {
        "type": "string",
        "enum": [
          "queued",
          "running",
          "completed",
          "failed",
          "aborted",
          "timed_out"
        ]
      },
      "depth": {
        "type": "integer",
        "minimum": 1,
        "maximum": 2
      },
      "maxDepth": {
        "type": "integer",
        "minimum": 1,
        "maximum": 2
      },
      "abortRequested": {
        "type": "boolean"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "completedAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      },
      "runs": {
        "type": "array",
        "minItems": 1,
        "maxItems": 2,
        "items": {
          "type": "object"
        }
      }
    }
  },
  "agent-subagent-run.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-subagent-run.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "id",
      "batchId",
      "childSessionId",
      "templateId",
      "templateVersion",
      "ordinal",
      "task",
      "state",
      "budget",
      "usage",
      "result",
      "error",
      "createdAtMs",
      "startedAtMs",
      "updatedAtMs",
      "completedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-subagent-run.v1"
      },
      "id": {
        "type": "string",
        "minLength": 1
      },
      "batchId": {
        "type": "string",
        "minLength": 1
      },
      "childSessionId": {
        "type": "string",
        "minLength": 1
      },
      "templateId": {
        "type": "string",
        "enum": [
          "researcher",
          "planner",
          "worker",
          "reviewer",
          "delegate"
        ]
      },
      "templateVersion": {
        "type": "string",
        "const": "1"
      },
      "ordinal": {
        "type": "integer",
        "minimum": 0,
        "maximum": 1
      },
      "task": {
        "type": "string",
        "minLength": 1,
        "maxLength": 8000
      },
      "state": {
        "type": "string",
        "enum": [
          "queued",
          "running",
          "completed",
          "failed",
          "aborted",
          "timed_out"
        ]
      },
      "budget": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "maxTurns",
          "maxToolCalls",
          "maxTotalTokens",
          "maxDurationMs",
          "maxOutputChars"
        ],
        "properties": {
          "maxTurns": {
            "type": "integer",
            "minimum": 0,
            "maximum": 32
          },
          "maxToolCalls": {
            "type": "integer",
            "minimum": 0,
            "maximum": 64
          },
          "maxTotalTokens": {
            "type": "integer",
            "minimum": 256,
            "maximum": 262144
          },
          "maxDurationMs": {
            "type": "integer",
            "minimum": 1000,
            "maximum": 900000
          },
          "maxOutputChars": {
            "type": "integer",
            "minimum": 256,
            "maximum": 100000
          }
        }
      },
      "usage": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "turnCount",
          "toolCount",
          "totalTokens"
        ],
        "properties": {
          "turnCount": {
            "type": "integer",
            "minimum": 0
          },
          "toolCount": {
            "type": "integer",
            "minimum": 0
          },
          "totalTokens": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "result": {
        "type": "object"
      },
      "error": {
        "type": "string",
        "maxLength": 500
      },
      "artifact": {
        "type": "object",
        "required": [
          "schemaVersion",
          "artifactId",
          "ownerKind",
          "ownerId",
          "kind",
          "sha256"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.agent-artifact-ref.v1"
          },
          "artifactId": {
            "type": "string",
            "minLength": 1
          },
          "ownerKind": {
            "type": "string",
            "const": "subagent_run"
          },
          "ownerId": {
            "type": "string",
            "minLength": 1
          },
          "kind": {
            "type": "string",
            "const": "lifecycle"
          },
          "sha256": {
            "type": "string"
          }
        }
      },
      "supervision": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "phase",
          "reason",
          "requestedAtMs",
          "graceMs"
        ],
        "properties": {
          "phase": {
            "type": "string",
            "enum": [
              "none",
              "soft",
              "hard",
              "forced"
            ]
          },
          "reason": {
            "type": "string",
            "maxLength": 240
          },
          "requestedAtMs": {
            "type": [
              "integer",
              "null"
            ],
            "minimum": 0
          },
          "graceMs": {
            "type": "integer",
            "minimum": 0,
            "maximum": 30000
          }
        }
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "startedAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "completedAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      }
    }
  },
  "agent-template.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-template.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "templateId",
      "version",
      "displayName",
      "summary",
      "contextModes",
      "toolProfileVersion",
      "budget",
      "capabilities"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-template.v1"
      },
      "templateId": {
        "type": "string",
        "enum": [
          "researcher",
          "planner",
          "worker",
          "reviewer",
          "delegate"
        ]
      },
      "version": {
        "type": "string",
        "const": "1"
      },
      "displayName": {
        "type": "string",
        "minLength": 1,
        "maxLength": 40
      },
      "summary": {
        "type": "string",
        "minLength": 1,
        "maxLength": 180
      },
      "contextModes": {
        "type": "array",
        "minItems": 1,
        "maxItems": 2,
        "uniqueItems": true,
        "items": {
          "type": "string",
          "enum": [
            "fresh",
            "fork"
          ]
        }
      },
      "toolProfileVersion": {
        "type": "string",
        "enum": [
          "subagent-readonly-v1",
          "subagent-worker-v1"
        ]
      },
      "budget": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "maxDepth",
          "maxTurns",
          "maxToolCalls",
          "maxTotalTokens",
          "maxDurationMs",
          "maxOutputChars"
        ],
        "properties": {
          "maxDepth": {
            "type": "integer",
            "minimum": 1,
            "maximum": 2
          },
          "maxTurns": {
            "type": "integer",
            "minimum": 0,
            "maximum": 32
          },
          "maxToolCalls": {
            "type": "integer",
            "minimum": 0,
            "maximum": 64
          },
          "maxTotalTokens": {
            "type": "integer",
            "minimum": 256,
            "maximum": 262144
          },
          "maxDurationMs": {
            "type": "integer",
            "minimum": 1000,
            "maximum": 900000
          },
          "maxOutputChars": {
            "type": "integer",
            "minimum": 256,
            "maximum": 100000
          }
        }
      },
      "capabilities": {
        "type": "array",
        "minItems": 1,
        "maxItems": 8,
        "uniqueItems": true,
        "items": {
          "type": "string",
          "enum": [
            "rag",
            "memory",
            "planning",
            "review",
            "control",
            "delegation"
          ]
        }
      }
    }
  },
  "agent-thinking-selection.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-thinking-selection.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "ok",
      "sessionId",
      "thinkingLevel",
      "selected"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-thinking-selection.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "thinkingLevel": {
        "type": "string",
        "enum": [
          "off",
          "minimal",
          "low",
          "medium",
          "high",
          "xhigh",
          "max"
        ]
      },
      "selected": {
        "type": [
          "object",
          "null"
        ]
      }
    }
  },
  "agent-tool-call.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-tool-call.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "sessionId",
      "tool",
      "toolCallId",
      "args"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-tool-call.v1"
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "tool": {
        "type": "string",
        "enum": [
          "ime_overview",
          "ime_input",
          "ime_voice",
          "ime_planning",
          "agent_schedule",
          "ime_memory",
          "agent_role_book",
          "ime_knowledge",
          "ime_models",
          "ime_runtime",
          "ime_configuration",
          "ime_agents",
          "ime_browser",
          "agent_plan",
          "desktop_semantic",
          "ime_plugins",
          "workspace_list",
          "workspace_read",
          "workspace_search",
          "workspace_patch",
          "workspace_shell"
        ]
      },
      "toolCallId": {
        "type": "string",
        "minLength": 1
      },
      "args": {
        "type": "object"
      },
      "runtimeContext": {
        "type": "object",
        "required": [
          "schemaVersion",
          "forkSessions"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.agent-runtime-context.v1"
          },
          "forkSessions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {
              "type": "object",
              "required": [
                "sessionId",
                "sessionFile",
                "parentSessionFile",
                "parentLeafId"
              ],
              "properties": {
                "sessionId": {
                  "type": "string",
                  "minLength": 1,
                  "maxLength": 128
                },
                "sessionFile": {
                  "type": "string",
                  "minLength": 1,
                  "maxLength": 4096
                },
                "parentSessionFile": {
                  "type": "string",
                  "minLength": 1,
                  "maxLength": 4096
                },
                "parentLeafId": {
                  "type": "string",
                  "minLength": 1,
                  "maxLength": 128
                },
                "thinkingOverride": {
                  "type": "string",
                  "enum": [
                    "off"
                  ]
                }
              },
              "additionalProperties": false
            }
          }
        },
        "additionalProperties": false
      }
    },
    "additionalProperties": false
  },
  "agent-tool-result.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.agent-tool-result.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "ok",
      "tool",
      "operation",
      "result"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.agent-tool-result.v1"
      },
      "ok": {
        "type": "boolean"
      },
      "tool": {
        "type": "string",
        "enum": [
          "ime_overview",
          "ime_input",
          "ime_voice",
          "ime_planning",
          "agent_schedule",
          "ime_memory",
          "agent_role_book",
          "ime_knowledge",
          "ime_models",
          "ime_runtime",
          "ime_configuration",
          "ime_agents",
          "ime_browser",
          "agent_plan",
          "desktop_semantic",
          "ime_plugins",
          "workspace_list",
          "workspace_read",
          "workspace_search",
          "workspace_patch",
          "workspace_shell"
        ]
      },
      "operation": {
        "type": "string",
        "enum": [
          "status",
          "capabilities",
          "recent_activity",
          "get_settings",
          "preview_settings",
          "apply_settings",
          "rollback_settings",
          "profile",
          "candidate_explain",
          "lexicon_review",
          "lexicon_apply",
          "lexicon_rollback",
          "privacy_policy",
          "provider_status",
          "provider_preview",
          "provider_apply",
          "provider_rollback",
          "dashboard",
          "task_action",
          "undo_task_event",
          "schedule",
          "runs",
          "pause",
          "resume",
          "cancel",
          "retry",
          "catalog",
          "read",
          "recent",
          "trace",
          "maintenance_status",
          "curation_prepare",
          "maintenance_preview",
          "maintenance_review",
          "maintenance_apply",
          "maintenance_rollback",
          "remember_preview",
          "correct_preview",
          "forget_preview",
          "remember_apply",
          "correct_apply",
          "forget_apply",
          "governance_rollback",
          "get",
          "explain",
          "history",
          "propose_revision",
          "review",
          "list",
          "inspect",
          "act",
          "update",
          "create_draft",
          "validate",
          "propose_install",
          "list_bases",
          "search",
          "find",
          "open",
          "recall",
          "deep_recall",
          "route_status",
          "profiles",
          "profile_preview",
          "profile_apply",
          "profile_rollback",
          "probe",
          "cache_stats",
          "health",
          "components",
          "diagnose",
          "pause_ai",
          "resume_ai",
          "restart_sidecar",
          "restart_predictor",
          "redeploy_rime",
          "audit",
          "export_preview",
          "export",
          "restore_preview",
          "restore_apply",
          "delegate",
          "artifact",
          "abort",
          "room_send",
          "room_ask",
          "room_reply",
          "room_mailbox",
          "room_assign",
          "room_submit",
          "room_accept",
          "room_return",
          "room_block",
          "room_escalate",
          "room_work",
          "tabs",
          "snapshot",
          "screenshot",
          "navigate",
          "click",
          "type",
          "scroll",
          "wait",
          "stop",
          "run",
          "apply"
        ]
      },
      "result": {
        "type": "object"
      }
    }
  },
  "assistant-candidate-action.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.assistant-candidate-action.v1",
    "type": "object",
    "required": [
      "action",
      "candidate"
    ],
    "properties": {
      "action": {
        "type": "string",
        "enum": [
          "remember",
          "suppress"
        ]
      },
      "candidate": {
        "type": "object",
        "properties": {
          "text": {
            "type": "string"
          },
          "insertText": {
            "type": "string"
          },
          "sourceType": {
            "type": "string"
          },
          "memoryId": {
            "type": "string"
          },
          "sourceEventId": {
            "type": [
              "integer",
              "null"
            ]
          },
          "suggestionId": {
            "type": "string"
          },
          "candidateStableId": {
            "type": "string"
          }
        },
        "additionalProperties": true
      },
      "query": {
        "type": "string"
      },
      "project": {
        "type": "string"
      },
      "app": {
        "type": "string"
      },
      "frontAppBundleId": {
        "type": "string"
      },
      "frontmostApp": {
        "type": "string"
      },
      "bundleId": {
        "type": "string"
      },
      "privacyDisposition": {
        "type": "string",
        "enum": [
          "allowed",
          "sensitive",
          "unknown"
        ]
      },
      "sensitiveField": {
        "type": "boolean"
      },
      "secureInput": {
        "type": "boolean"
      }
    },
    "additionalProperties": false
  },
  "assistant-overlay.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.assistant-overlay.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "visible",
      "uiMode",
      "phase",
      "inputMode",
      "candidates",
      "keyPolicy",
      "frontendTransaction"
    ],
    "properties": {
      "schemaVersion": {
        "const": "rag-ime.assistant-overlay.v1"
      },
      "visible": {
        "type": "boolean"
      },
      "uiMode": {
        "type": "string"
      },
      "phase": {
        "type": "string"
      },
      "inputMode": {
        "type": "string"
      },
      "statusText": {
        "type": "string"
      },
      "snapshotId": {
        "type": "string"
      },
      "sessionFingerprint": {
        "type": "string"
      },
      "expiresAfterMs": {
        "type": "integer",
        "minimum": 0
      },
      "candidates": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/candidate"
        }
      },
      "sourceCards": {
        "type": "array"
      },
      "keyPolicy": {
        "type": "object"
      },
      "overlayConfig": {
        "type": "object"
      },
      "progressive": {
        "type": "object"
      },
      "frontendTransaction": {
        "type": "object"
      },
      "dismissReason": {
        "type": "string"
      }
    },
    "$defs": {
      "candidate": {
        "type": "object",
        "required": [
          "insertText",
          "sourceType"
        ],
        "properties": {
          "text": {
            "type": "string"
          },
          "insertText": {
            "type": "string",
            "minLength": 1
          },
          "sourceType": {
            "type": "string",
            "enum": [
              "model",
              "rag",
              "memory",
              "action"
            ]
          },
          "candidateStableId": {
            "type": "string"
          },
          "snapshotId": {
            "type": "string"
          },
          "selectionAction": {
            "type": "string"
          },
          "sourceBadge": {
            "type": "string"
          },
          "memoryId": {
            "type": "string"
          },
          "suggestionId": {
            "type": "string"
          },
          "sourceEventId": {
            "type": [
              "integer",
              "null"
            ]
          },
          "metadata": {
            "type": "object"
          }
        }
      }
    }
  },
  "control-tool-manifest.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.control-tool-manifest.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "id",
      "domain",
      "displayName",
      "description",
      "category",
      "riskLevel",
      "sessionModes",
      "operations",
      "resultPresentation",
      "availability",
      "version"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.control-tool-manifest.v1"
      },
      "id": {
        "type": "string",
        "minLength": 1
      },
      "domain": {
        "type": "string",
        "minLength": 1
      },
      "displayName": {
        "type": "string",
        "minLength": 1
      },
      "description": {
        "type": "string",
        "minLength": 1
      },
      "category": {
        "type": "string",
        "enum": [
          "overview",
          "input",
          "voice",
          "planning",
          "memory",
          "knowledge",
          "models",
          "runtime",
          "configuration",
          "agents",
          "browser",
          "desktop",
          "workspace"
        ]
      },
      "riskLevel": {
        "type": "string",
        "enum": [
          "R0",
          "R1",
          "R2",
          "R3"
        ]
      },
      "operationRisks": {
        "type": "object",
        "additionalProperties": {
          "type": "string",
          "enum": [
            "R0",
            "R1",
            "R2",
            "R3"
          ]
        }
      },
      "sessionModes": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": [
            "assistant",
            "coordinator"
          ]
        }
      },
      "operations": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "resultPresentation": {
        "type": "string",
        "enum": [
          "status",
          "table",
          "citation",
          "tool_result",
          "diff",
          "approval",
          "terminal",
          "media"
        ]
      },
      "availability": {
        "type": "string",
        "enum": [
          "online",
          "offline",
          "disabled",
          "unconfigured"
        ]
      },
      "version": {
        "type": "string",
        "minLength": 1
      }
    }
  },
  "daily-activity-timeline.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.daily-activity-timeline.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "timelineId",
      "project",
      "date",
      "timezone",
      "status",
      "sourceEventIds",
      "sourceEventHash",
      "segments",
      "summary",
      "eventCount",
      "segmentCount",
      "approvedBookId",
      "approvedBy",
      "approvedAtMs",
      "createdAtMs",
      "updatedAtMs",
      "policy"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.daily-activity-timeline.v1"
      },
      "timelineId": {
        "type": "string",
        "minLength": 1
      },
      "project": {
        "type": "string"
      },
      "date": {
        "type": "string",
        "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
      },
      "timezone": {
        "type": "string",
        "minLength": 1
      },
      "status": {
        "type": "string",
        "enum": [
          "draft",
          "approved",
          "rejected",
          "superseded"
        ]
      },
      "sourceEventIds": {
        "type": "array",
        "items": {
          "type": "integer",
          "minimum": 1
        },
        "uniqueItems": true
      },
      "sourceEventHash": {
        "type": "string",
        "pattern": "^[a-f0-9]{64}$"
      },
      "segments": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/segment"
        }
      },
      "summary": {
        "type": "string",
        "minLength": 1
      },
      "eventCount": {
        "type": "integer",
        "minimum": 1
      },
      "segmentCount": {
        "type": "integer",
        "minimum": 1
      },
      "approvedBookId": {
        "type": "string"
      },
      "approvedBy": {
        "type": "string"
      },
      "approvedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "segmentationMode": {
        "type": "string",
        "enum": [
          "semantic_task_v2",
          "legacy_app_interval_v1"
        ]
      },
      "source": {
        "$ref": "#/$defs/source"
      },
      "ref": {
        "$ref": "#/$defs/ref"
      },
      "policy": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "derivedFromInputEvents",
          "longTermFact",
          "automaticPromotion",
          "explicitApprovalRequired"
        ],
        "properties": {
          "derivedFromInputEvents": {
            "type": "boolean",
            "const": true
          },
          "longTermFact": {
            "type": "boolean",
            "const": false
          },
          "automaticPromotion": {
            "type": "boolean",
            "const": false
          },
          "explicitApprovalRequired": {
            "type": "boolean",
            "const": true
          }
        }
      }
    },
    "$defs": {
      "segment": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "segmentId",
          "position",
          "app",
          "sourceKinds",
          "contextGroupIds",
          "startMs",
          "endMs",
          "period",
          "eventCount",
          "sourceEventIds",
          "sourceEventHash",
          "summary",
          "redactedEventCount"
        ],
        "properties": {
          "segmentId": {
            "type": "string",
            "minLength": 1
          },
          "position": {
            "type": "integer",
            "minimum": 0
          },
          "app": {
            "type": "string",
            "minLength": 1
          },
          "sourceKinds": {
            "type": "array",
            "items": {
              "type": "string",
              "minLength": 1
            },
            "uniqueItems": true
          },
          "contextGroupIds": {
            "type": "array",
            "items": {
              "type": "string",
              "minLength": 1
            },
            "uniqueItems": true
          },
          "startMs": {
            "type": "integer",
            "minimum": 0
          },
          "endMs": {
            "type": "integer",
            "minimum": 0
          },
          "period": {
            "type": "string",
            "enum": [
              "day",
              "morning",
              "afternoon",
              "evening"
            ]
          },
          "eventCount": {
            "type": "integer",
            "minimum": 1
          },
          "sourceEventIds": {
            "type": "array",
            "items": {
              "type": "integer",
              "minimum": 1
            },
            "uniqueItems": true
          },
          "sourceEventHash": {
            "type": "string",
            "pattern": "^[a-f0-9]{64}$"
          },
          "summary": {
            "type": "string",
            "minLength": 1
          },
          "redactedEventCount": {
            "type": "integer",
            "minimum": 0
          },
          "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "apps": {
            "type": "array",
            "items": {
              "type": "string",
              "minLength": 1
            },
            "uniqueItems": true
          },
          "evidenceRefs": {
            "type": "array",
            "items": {
              "$ref": "#/$defs/evidenceRef"
            }
          },
          "source": {
            "$ref": "#/$defs/source"
          },
          "ref": {
            "$ref": "#/$defs/ref"
          }
        }
      },
      "source": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "type",
          "id"
        ],
        "properties": {
          "type": {
            "type": "string"
          },
          "id": {
            "type": "string"
          }
        }
      },
      "ref": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "type",
          "id"
        ],
        "properties": {
          "type": {
            "type": "string"
          },
          "id": {
            "type": "string"
          }
        }
      },
      "evidenceRef": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "sourceType",
          "sourceId",
          "eventId",
          "app",
          "sourceKind",
          "occurredAtMs",
          "preview"
        ],
        "properties": {
          "sourceType": {
            "type": "string",
            "const": "input_event"
          },
          "sourceId": {
            "type": "string",
            "minLength": 1
          },
          "eventId": {
            "type": "integer",
            "minimum": 1
          },
          "app": {
            "type": "string",
            "minLength": 1
          },
          "sourceKind": {
            "type": "string",
            "minLength": 1
          },
          "occurredAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "preview": {
            "type": "string",
            "minLength": 1,
            "maxLength": 180
          }
        }
      }
    }
  },
  "daily-conversation-digest.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.daily-conversation-digest.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "digestId",
      "project",
      "roleId",
      "window",
      "sourceEvidenceIds",
      "activityTimelineId",
      "activityContext",
      "sourceCounts",
      "summary",
      "highlights",
      "recentWork",
      "caveats",
      "generatedAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.daily-conversation-digest.v1"
      },
      "digestId": {
        "type": "string",
        "minLength": 1
      },
      "project": {
        "type": "string"
      },
      "roleId": {
        "type": "string",
        "minLength": 1
      },
      "window": {
        "type": "object",
        "required": [
          "startMs",
          "endMs"
        ],
        "properties": {
          "startMs": {
            "type": "integer",
            "minimum": 0
          },
          "endMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "sourceEvidenceIds": {
        "type": "array",
        "items": {
          "type": "string",
          "minLength": 1
        }
      },
      "activityTimelineId": {
        "type": "string"
      },
      "activityContext": {
        "$ref": "#/$defs/activityContext"
      },
      "sourceCounts": {
        "type": "object"
      },
      "summary": {
        "type": "string",
        "minLength": 1
      },
      "highlights": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/digestItem"
        }
      },
      "recentWork": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/digestItem"
        }
      },
      "caveats": {
        "type": "array",
        "items": {
          "type": "string",
          "minLength": 1
        }
      },
      "generatedAtMs": {
        "type": "integer",
        "minimum": 0
      }
    },
    "$defs": {
      "activityContext": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "schemaVersion",
          "available",
          "date",
          "timelineId",
          "status",
          "sourceEventHash",
          "summary",
          "segments",
          "eventCount",
          "retainedEventCount",
          "filteredInternalEventCount",
          "deduplicatedEventCount",
          "redactedEventCount",
          "corroborationOnly",
          "maySupportFacts"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.activity-timeline-context.v1"
          },
          "available": {
            "type": "boolean"
          },
          "date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
          },
          "timelineId": {
            "type": "string"
          },
          "status": {
            "type": "string",
            "enum": [
              "unavailable",
              "draft",
              "approved"
            ]
          },
          "sourceEventHash": {
            "type": "string",
            "pattern": "^$|^[a-f0-9]{64}$"
          },
          "summary": {
            "type": "string",
            "maxLength": 2400
          },
          "segments": {
            "type": "array",
            "maxItems": 12,
            "items": {
              "type": "object"
            }
          },
          "eventCount": {
            "type": "integer",
            "minimum": 0
          },
          "retainedEventCount": {
            "type": "integer",
            "minimum": 0
          },
          "filteredInternalEventCount": {
            "type": "integer",
            "minimum": 0
          },
          "deduplicatedEventCount": {
            "type": "integer",
            "minimum": 0
          },
          "redactedEventCount": {
            "type": "integer",
            "minimum": 0
          },
          "corroborationOnly": {
            "type": "boolean",
            "const": true
          },
          "maySupportFacts": {
            "type": "boolean",
            "const": false
          }
        }
      },
      "digestItem": {
        "type": "object",
        "required": [
          "evidenceId",
          "sourceKind",
          "text",
          "occurredAtMs"
        ],
        "properties": {
          "evidenceId": {
            "type": "string",
            "minLength": 1
          },
          "sourceKind": {
            "type": "string",
            "minLength": 1
          },
          "text": {
            "type": "string",
            "minLength": 1
          },
          "occurredAtMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      }
    }
  },
  "foreground-commit.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.foreground-commit.v1",
    "type": "object",
    "required": [
      "text"
    ],
    "properties": {
      "text": {
        "type": "string",
        "minLength": 1
      },
      "recentContext": {
        "type": "string"
      },
      "preedit": {
        "type": "string"
      },
      "project": {
        "type": "string"
      },
      "app": {
        "type": "string"
      },
      "frontAppBundleId": {
        "type": "string"
      },
      "frontmostApp": {
        "type": "string"
      },
      "bundleId": {
        "type": "string"
      },
      "candidateRank": {
        "type": [
          "integer",
          "null"
        ]
      },
      "providerName": {
        "type": "string"
      },
      "tags": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "source": {
        "type": "string"
      },
      "contextGroupId": {
        "type": "string"
      },
      "contextGroupLevel": {
        "type": "string"
      },
      "privacyDisposition": {
        "type": "string",
        "enum": [
          "allowed",
          "sensitive",
          "unknown"
        ]
      },
      "sensitiveField": {
        "type": "boolean"
      },
      "secureInput": {
        "type": "boolean"
      }
    },
    "additionalProperties": false
  },
  "foreground-context.v2": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.foreground-context.v2",
    "type": "object",
    "required": [
      "available",
      "source",
      "freshnessMs",
      "canReplaceSelection"
    ],
    "properties": {
      "available": {
        "type": "boolean"
      },
      "source": {
        "type": "string"
      },
      "freshnessMs": {
        "type": "integer",
        "minimum": 0
      },
      "capturedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "surroundingBefore": {
        "type": "string"
      },
      "surroundingAfter": {
        "type": "string"
      },
      "selectedText": {
        "type": "string"
      },
      "selectedTextHash": {
        "type": "string"
      },
      "canReplaceSelection": {
        "type": "boolean"
      },
      "contextGroupId": {
        "type": "string"
      },
      "contextGroupLevel": {
        "type": "string",
        "enum": [
          "document",
          "project",
          "app",
          "global",
          ""
        ]
      }
    }
  },
  "frontend-capabilities.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.frontend-capabilities.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "gatewayVersion",
      "contracts",
      "features",
      "adapterBoundary",
      "legacyCompatibility"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.frontend-capabilities.v1"
      },
      "gatewayVersion": {
        "type": "string",
        "const": "rag-ime.frontend-gateway.v1"
      },
      "contracts": {
        "type": "object"
      },
      "features": {
        "type": "object"
      },
      "adapterBoundary": {
        "type": "object"
      },
      "legacyCompatibility": {
        "type": "object"
      }
    }
  },
  "frontend-selection-response.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.frontend-selection-response.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "gatewayVersion",
      "ok",
      "session",
      "selectionReceipt",
      "eventId",
      "origin",
      "insertText",
      "recordedActionCount",
      "privacy",
      "backendContract"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.frontend-selection-response.v1"
      },
      "gatewayVersion": {
        "type": "string",
        "const": "rag-ime.frontend-gateway.v1"
      },
      "ok": {
        "type": "boolean"
      },
      "session": {
        "$ref": "#/$defs/session"
      },
      "selectionReceipt": {
        "$ref": "#/$defs/selectionReceipt"
      },
      "eventId": {
        "type": "string"
      },
      "origin": {
        "type": "string"
      },
      "insertText": {
        "type": "string"
      },
      "recordedActionCount": {
        "type": "integer",
        "minimum": 0
      },
      "privacy": {
        "type": "object"
      },
      "backendContract": {
        "type": "string"
      }
    },
    "$defs": {
      "session": {
        "type": "object",
        "required": [
          "id",
          "requestSeq",
          "inputGeneration"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1
          },
          "requestSeq": {
            "type": "integer",
            "minimum": 0
          },
          "inputGeneration": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "selectionReceipt": {
        "type": "object",
        "required": [
          "sessionId",
          "requestSeq",
          "inputGeneration",
          "snapshotId",
          "snapshotGeneration",
          "candidateId",
          "requestConsistencyValidated",
          "runtimeFreshnessValidated"
        ],
        "properties": {
          "sessionId": {
            "type": "string",
            "minLength": 1
          },
          "requestSeq": {
            "type": "integer",
            "minimum": 0
          },
          "inputGeneration": {
            "type": "integer",
            "minimum": 0
          },
          "snapshotId": {
            "type": "string",
            "minLength": 1
          },
          "snapshotGeneration": {
            "type": "integer",
            "minimum": 0
          },
          "candidateId": {
            "type": "string",
            "minLength": 1
          },
          "requestConsistencyValidated": {
            "type": "boolean"
          },
          "runtimeFreshnessValidated": {
            "type": "boolean"
          }
        }
      }
    }
  },
  "frontend-selection.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.frontend-selection.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "frontend",
      "session",
      "privacy",
      "candidate"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.frontend-selection.v1"
      },
      "frontend": {
        "type": "object"
      },
      "session": {
        "$ref": "#/$defs/session"
      },
      "privacy": {
        "type": "object",
        "required": [
          "disposition"
        ],
        "properties": {
          "disposition": {
            "type": "string",
            "enum": [
              "allowed",
              "sensitive",
              "unknown"
            ]
          },
          "reason": {
            "type": "string"
          },
          "sensitiveField": {
            "type": "boolean"
          },
          "secureInput": {
            "type": "boolean"
          }
        }
      },
      "candidate": {
        "$ref": "#/$defs/candidate"
      },
      "visibleCandidates": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/candidate"
        }
      },
      "context": {
        "type": "object"
      },
      "providerName": {
        "type": "string"
      },
      "dryRun": {
        "type": "boolean"
      }
    },
    "$defs": {
      "candidate": {
        "type": "object",
        "required": [
          "id",
          "snapshotId",
          "snapshotGeneration",
          "inputGeneration",
          "text",
          "insertText",
          "origin"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1
          },
          "snapshotId": {
            "type": "string",
            "minLength": 1
          },
          "snapshotGeneration": {
            "type": "integer",
            "minimum": 0
          },
          "inputGeneration": {
            "type": "integer",
            "minimum": 0
          },
          "label": {
            "type": "string"
          },
          "text": {
            "type": "string"
          },
          "insertText": {
            "type": "string",
            "minLength": 1
          },
          "origin": {
            "type": "string",
            "enum": [
              "native",
              "model",
              "retrieval",
              "memory",
              "action",
              "status",
              "literal",
              "assistant"
            ]
          },
          "rank": {
            "type": "integer",
            "minimum": 1
          },
          "nativeIndex": {
            "type": [
              "integer",
              "null"
            ]
          },
          "selectionAction": {
            "type": "string"
          },
          "suggestionId": {
            "type": "string"
          },
          "memoryId": {
            "type": "string"
          },
          "sourceEventId": {
            "type": [
              "integer",
              "null"
            ]
          },
          "metadata": {
            "type": "object"
          }
        }
      },
      "session": {
        "type": "object",
        "required": [
          "id",
          "requestSeq",
          "inputGeneration"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1
          },
          "requestSeq": {
            "type": "integer",
            "minimum": 0
          },
          "inputGeneration": {
            "type": "integer",
            "minimum": 0
          }
        }
      }
    }
  },
  "frontend-suggest-request.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.frontend-suggest-request.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "frontend",
      "session",
      "privacy",
      "input"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.frontend-suggest-request.v1"
      },
      "frontend": {
        "$ref": "#/$defs/frontend"
      },
      "session": {
        "$ref": "#/$defs/session"
      },
      "privacy": {
        "$ref": "#/$defs/privacy"
      },
      "input": {
        "$ref": "#/$defs/input"
      },
      "context": {
        "type": "object"
      },
      "nativeCandidates": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/nativeCandidate"
        }
      },
      "nativeState": {
        "type": "object"
      },
      "limits": {
        "type": "object"
      },
      "flags": {
        "type": "object"
      }
    },
    "$defs": {
      "frontend": {
        "type": "object",
        "required": [
          "id",
          "platform",
          "inputEngine"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1
          },
          "build": {
            "type": "string"
          },
          "platform": {
            "type": "string",
            "minLength": 1
          },
          "inputFramework": {
            "type": "string"
          },
          "inputEngine": {
            "type": "string",
            "minLength": 1
          }
        }
      },
      "session": {
        "type": "object",
        "required": [
          "id",
          "requestSeq",
          "inputGeneration"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1
          },
          "requestSeq": {
            "type": "integer",
            "minimum": 0
          },
          "inputGeneration": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "privacy": {
        "type": "object",
        "required": [
          "disposition"
        ],
        "properties": {
          "disposition": {
            "type": "string",
            "enum": [
              "allowed",
              "sensitive",
              "unknown"
            ]
          },
          "reason": {
            "type": "string"
          },
          "sensitiveField": {
            "type": "boolean"
          },
          "secureInput": {
            "type": "boolean"
          }
        }
      },
      "input": {
        "type": "object",
        "properties": {
          "raw": {
            "type": "string"
          },
          "preedit": {
            "type": "string"
          },
          "commitPreview": {
            "type": "string"
          },
          "committedContext": {
            "type": "string"
          },
          "idleMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "nativeCandidate": {
        "type": "object",
        "required": [
          "text"
        ],
        "properties": {
          "id": {
            "type": "string"
          },
          "label": {
            "type": "string"
          },
          "text": {
            "type": "string",
            "minLength": 1
          },
          "annotation": {
            "type": "string"
          },
          "rank": {
            "type": "integer",
            "minimum": 1
          },
          "nativeIndex": {
            "type": "integer",
            "minimum": 0
          },
          "metadata": {
            "type": "object"
          }
        }
      }
    }
  },
  "frontend-suggest-response.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.frontend-suggest-response.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "gatewayVersion",
      "frontend",
      "session",
      "input",
      "candidates",
      "presentation",
      "selectionPolicy",
      "predictionSession",
      "privacy"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.frontend-suggest-response.v1"
      },
      "gatewayVersion": {
        "type": "string",
        "const": "rag-ime.frontend-gateway.v1"
      },
      "frontend": {
        "type": "object"
      },
      "session": {
        "$ref": "#/$defs/session"
      },
      "input": {
        "type": "object"
      },
      "candidates": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/candidate"
        }
      },
      "presentation": {
        "type": "object"
      },
      "selectionPolicy": {
        "type": "object"
      },
      "predictionSession": {
        "type": "object"
      },
      "progressive": {
        "type": "object"
      },
      "privacy": {
        "type": "object"
      },
      "diagnostics": {
        "type": "object"
      }
    },
    "$defs": {
      "candidate": {
        "type": "object",
        "required": [
          "id",
          "snapshotId",
          "snapshotGeneration",
          "inputGeneration",
          "text",
          "insertText",
          "origin",
          "rank",
          "selectionAction"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1
          },
          "snapshotId": {
            "type": "string",
            "minLength": 1
          },
          "snapshotGeneration": {
            "type": "integer",
            "minimum": 0
          },
          "inputGeneration": {
            "type": "integer",
            "minimum": 0
          },
          "label": {
            "type": "string"
          },
          "text": {
            "type": "string"
          },
          "insertText": {
            "type": "string"
          },
          "origin": {
            "type": "string",
            "enum": [
              "native",
              "model",
              "retrieval",
              "memory",
              "action",
              "status",
              "literal",
              "assistant"
            ]
          },
          "provider": {
            "type": "string"
          },
          "rank": {
            "type": "integer",
            "minimum": 1
          },
          "nativeIndex": {
            "type": [
              "integer",
              "null"
            ]
          },
          "selectionAction": {
            "type": "string"
          },
          "metadata": {
            "type": "object"
          }
        }
      },
      "session": {
        "type": "object",
        "required": [
          "id",
          "requestSeq",
          "inputGeneration"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1
          },
          "requestSeq": {
            "type": "integer",
            "minimum": 0
          },
          "inputGeneration": {
            "type": "integer",
            "minimum": 0
          }
        }
      }
    }
  },
  "knowledge-document-detail.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://rag-ime.local/contracts/knowledge-document-detail.v1.json",
    "title": "RAG-IME Knowledge Document Detail",
    "type": "object",
    "required": [
      "schemaVersion",
      "document",
      "chunks",
      "pages",
      "assets",
      "tables",
      "artifact",
      "contentWindow"
    ],
    "properties": {
      "schemaVersion": {
        "const": "rag-ime.knowledge-library.v1"
      },
      "document": {
        "type": "object",
        "required": [
          "documentId",
          "kbId",
          "fileName",
          "mimeType",
          "byteSize",
          "sha256",
          "status",
          "sourceReadPath"
        ],
        "properties": {
          "documentId": {
            "type": "string",
            "minLength": 1
          },
          "kbId": {
            "type": "string",
            "minLength": 1
          },
          "fileName": {
            "type": "string",
            "minLength": 1
          },
          "mimeType": {
            "type": "string",
            "minLength": 1
          },
          "byteSize": {
            "type": "integer",
            "minimum": 0
          },
          "sha256": {
            "type": "string",
            "pattern": "^[a-f0-9]{64}$"
          },
          "status": {
            "enum": [
              "queued",
              "parsing",
              "indexing",
              "ready",
              "stale",
              "failed",
              "deleting"
            ]
          },
          "pageCount": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100000
          },
          "sourceReadPath": {
            "type": "string",
            "pattern": "^/api/knowledge-bases/"
          }
        },
        "additionalProperties": true
      },
      "chunks": {
        "type": "object",
        "required": [
          "items",
          "offset",
          "limit",
          "total",
          "hasMore"
        ],
        "properties": {
          "items": {
            "type": "array"
          },
          "offset": {
            "type": "integer",
            "minimum": 0
          },
          "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500
          },
          "total": {
            "type": "integer",
            "minimum": 0
          },
          "hasMore": {
            "type": "boolean"
          }
        },
        "additionalProperties": false
      },
      "pages": {
        "type": "array"
      },
      "assets": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "assetId",
            "name",
            "mimeType",
            "byteSize",
            "sha256",
            "readPath"
          ],
          "properties": {
            "assetId": {
              "type": "string",
              "pattern": "^[a-f0-9]{64}$"
            },
            "name": {
              "type": "string"
            },
            "mimeType": {
              "enum": [
                "image/png",
                "image/jpeg",
                "image/gif",
                "image/webp",
                "image/bmp"
              ]
            },
            "byteSize": {
              "type": "integer",
              "minimum": 0,
              "maximum": 26214400
            },
            "sha256": {
              "type": "string",
              "pattern": "^[a-f0-9]{64}$"
            },
            "readPath": {
              "type": "string",
              "pattern": "^/api/knowledge-bases/"
            }
          },
          "additionalProperties": false
        }
      },
      "tables": {
        "type": "array",
        "maxItems": 32,
        "items": {
          "type": "object",
          "required": [
            "tableId",
            "title",
            "page",
            "columns",
            "rows",
            "markdown"
          ],
          "properties": {
            "tableId": {
              "type": "string",
              "minLength": 1
            },
            "title": {
              "type": "string",
              "maxLength": 300
            },
            "page": {
              "type": [
                "integer",
                "null"
              ],
              "minimum": 1
            },
            "columns": {
              "type": "array",
              "maxItems": 32,
              "items": {
                "type": "string",
                "maxLength": 500
              }
            },
            "rows": {
              "type": "array",
              "maxItems": 200,
              "items": {
                "type": "array",
                "maxItems": 32,
                "items": {
                  "type": "string",
                  "maxLength": 500
                }
              }
            },
            "markdown": {
              "type": "string",
              "maxLength": 64000
            }
          },
          "additionalProperties": false
        }
      },
      "artifact": {
        "type": "object"
      },
      "contentWindow": {
        "type": "object"
      }
    },
    "additionalProperties": false
  },
  "knowledge-document-import.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://rag-ime.local/contracts/knowledge-document-import.v1.json",
    "title": "RAG-IME Knowledge Document Import Receipt",
    "type": "object",
    "required": [
      "schemaVersion",
      "ok",
      "receipt"
    ],
    "properties": {
      "schemaVersion": {
        "const": "rag-ime.knowledge-document-import.v1"
      },
      "ok": {
        "const": true
      },
      "receipt": {
        "type": "object",
        "required": [
          "kbId",
          "documentId",
          "fileName",
          "mimeType",
          "byteSize",
          "sha256",
          "status"
        ],
        "properties": {
          "kbId": {
            "type": "string",
            "minLength": 1
          },
          "documentId": {
            "type": "string",
            "minLength": 1
          },
          "fileName": {
            "type": "string",
            "minLength": 1
          },
          "mimeType": {
            "type": "string",
            "minLength": 1
          },
          "byteSize": {
            "type": "integer",
            "minimum": 0
          },
          "sha256": {
            "type": "string",
            "pattern": "^[a-f0-9]{64}$"
          },
          "status": {
            "enum": [
              "queued",
              "parsing",
              "indexing",
              "ready",
              "stale",
              "failed",
              "deleting"
            ]
          }
        },
        "additionalProperties": false
      }
    },
    "additionalProperties": false
  },
  "knowledge-graph.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.knowledge-graph.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "kbId",
      "revision",
      "sourceRevision",
      "status",
      "updatedAtMs",
      "nodes",
      "edges",
      "stats",
      "truncated"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.knowledge-graph.v1"
      },
      "kbId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 160
      },
      "revision": {
        "type": "integer",
        "minimum": 0
      },
      "sourceRevision": {
        "type": "string",
        "pattern": "^sha256:[0-9a-f]{64}$"
      },
      "status": {
        "type": "string",
        "enum": [
          "ready",
          "building",
          "stale",
          "failed"
        ]
      },
      "updatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "jobId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 160
      },
      "error": {
        "type": "string",
        "minLength": 1,
        "maxLength": 2000
      },
      "extractor": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "mode",
          "model",
          "configured",
          "degraded"
        ],
        "properties": {
          "mode": {
            "type": "string",
            "enum": [
              "deterministic",
              "model"
            ]
          },
          "model": {
            "type": "string",
            "maxLength": 160
          },
          "configured": {
            "type": "boolean"
          },
          "degraded": {
            "type": "boolean"
          },
          "fingerprint": {
            "type": "string",
            "maxLength": 160
          },
          "processedChunkCount": {
            "type": "integer",
            "minimum": 0
          },
          "cachedChunkCount": {
            "type": "integer",
            "minimum": 0
          },
          "modelChunkCount": {
            "type": "integer",
            "minimum": 0
          },
          "fallbackChunkCount": {
            "type": "integer",
            "minimum": 0
          },
          "errorCount": {
            "type": "integer",
            "minimum": 0
          },
          "batchSize": {
            "type": "integer",
            "minimum": 1,
            "maximum": 8
          },
          "batchCount": {
            "type": "integer",
            "minimum": 0
          },
          "extractionConcurrency": {
            "type": "integer",
            "minimum": 1,
            "maximum": 4
          },
          "effectiveExtractionConcurrency": {
            "type": "integer",
            "minimum": 0,
            "maximum": 4
          },
          "entityCount": {
            "type": "integer",
            "minimum": 0
          },
          "termCount": {
            "type": "integer",
            "minimum": 0
          },
          "topicCount": {
            "type": "integer",
            "minimum": 0
          },
          "relationCount": {
            "type": "integer",
            "minimum": 0
          },
          "lastError": {
            "type": "string",
            "maxLength": 500
          }
        }
      },
      "nodes": {
        "type": "array",
        "maxItems": 1000,
        "items": {
          "$ref": "#/$defs/node"
        }
      },
      "edges": {
        "type": "array",
        "maxItems": 3000,
        "items": {
          "$ref": "#/$defs/edge"
        }
      },
      "stats": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "nodeCount",
          "edgeCount",
          "documentCount",
          "chunkCount",
          "indexedDocumentCount",
          "pendingDocumentCount"
        ],
        "properties": {
          "nodeCount": {
            "type": "integer",
            "minimum": 0
          },
          "edgeCount": {
            "type": "integer",
            "minimum": 0
          },
          "documentCount": {
            "type": "integer",
            "minimum": 0
          },
          "chunkCount": {
            "type": "integer",
            "minimum": 0
          },
          "indexedDocumentCount": {
            "type": "integer",
            "minimum": 0
          },
          "pendingDocumentCount": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "truncated": {
        "type": "boolean"
      }
    },
    "$defs": {
      "node": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "id",
          "label",
          "kind",
          "weight"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "kind": {
            "type": "string",
            "enum": [
              "document",
              "chunk",
              "topic",
              "entity",
              "term"
            ]
          },
          "documentId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "documentName": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512
          },
          "documentIds": {
            "type": "array",
            "maxItems": 1000,
            "uniqueItems": true,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 160
            }
          },
          "chunkId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "heading": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500
          },
          "excerpt": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "page": {
            "type": "integer",
            "minimum": 0
          },
          "weight": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          }
        }
      },
      "edge": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "id",
          "source",
          "target",
          "kind",
          "weight"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "source": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "target": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "kind": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64
          },
          "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120
          },
          "weight": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          }
        }
      }
    }
  },
  "knowledge-library.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://rag-ime.local/contracts/knowledge-library.v1.json",
    "title": "RAG-IME Document Knowledge Library",
    "type": "object",
    "required": [
      "schemaVersion"
    ],
    "properties": {
      "schemaVersion": {
        "const": "rag-ime.knowledge-library.v1"
      },
      "bases": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "id",
            "name",
            "parserMode",
            "agentEnabled"
          ],
          "properties": {
            "id": {
              "type": "string",
              "minLength": 1
            },
            "name": {
              "type": "string",
              "minLength": 1
            },
            "description": {
              "type": "string"
            },
            "parserMode": {
              "enum": [
                "auto",
                "builtin",
                "mineru"
              ]
            },
            "agentEnabled": {
              "type": "boolean"
            },
            "chunkingConfig": {
              "$ref": "#/$defs/chunkingConfig"
            },
            "retrievalConfig": {
              "$ref": "#/$defs/retrievalConfig"
            },
            "configRevision": {
              "type": "integer",
              "minimum": 1
            }
          },
          "additionalProperties": true
        }
      },
      "items": {
        "type": "array"
      }
    },
    "$defs": {
      "chunkingConfig": {
        "type": "object",
        "required": [
          "strategy",
          "size",
          "overlap",
          "separator",
          "respectHeadings",
          "respectPageBoundaries"
        ],
        "properties": {
          "strategy": {
            "enum": [
              "general",
              "markdown",
              "book",
              "qa",
              "laws",
              "separator",
              "fixed"
            ]
          },
          "size": {
            "type": "integer",
            "minimum": 200,
            "maximum": 8000
          },
          "overlap": {
            "type": "integer",
            "minimum": 0,
            "maximum": 2000
          },
          "separator": {
            "type": "string",
            "maxLength": 100
          },
          "respectHeadings": {
            "type": "boolean"
          },
          "respectPageBoundaries": {
            "type": "boolean"
          }
        },
        "additionalProperties": false
      },
      "retrievalConfig": {
        "type": "object",
        "required": [
          "mode",
          "topK",
          "threshold",
          "lexicalWeight",
          "denseWeight",
          "rrfK",
          "candidateMultiplier"
        ],
        "properties": {
          "mode": {
            "enum": [
              "lexical",
              "hybrid",
              "dense"
            ]
          },
          "topK": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100
          },
          "threshold": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "lexicalWeight": {
            "type": "number",
            "minimum": 0,
            "maximum": 10
          },
          "denseWeight": {
            "type": "number",
            "minimum": 0,
            "maximum": 10
          },
          "rrfK": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000
          },
          "candidateMultiplier": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20
          }
        },
        "additionalProperties": false
      }
    },
    "additionalProperties": true
  },
  "management-work-error.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.management-work-error.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "ok",
      "errorCode",
      "error",
      "currentRevision"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.management-work-error.v1"
      },
      "ok": {
        "type": "boolean",
        "const": false
      },
      "errorCode": {
        "type": "string",
        "enum": [
          "confirmation_mismatch",
          "domain_not_applicable",
          "domain_not_found",
          "domain_rejected",
          "domain_scope_mismatch",
          "invalid_payload",
          "invalid_request",
          "payload_hash_mismatch",
          "payload_too_large",
          "preview_already_used",
          "preview_expired",
          "preview_not_found",
          "preview_path_mismatch",
          "receipt_already_rolled_back",
          "receipt_not_found",
          "receipt_path_mismatch",
          "revision_mismatch",
          "rollback_authority_mismatch",
          "rollback_path_mismatch",
          "rollback_state_changed",
          "rollback_token_mismatch",
          "rollback_unavailable",
          "stored_contract_invalid",
          "unsupported_backend",
          "unsupported_mutation"
        ]
      },
      "error": {
        "type": "string",
        "minLength": 1
      },
      "currentRevision": {
        "type": "object"
      }
    }
  },
  "management-work-preview.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.management-work-preview.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "ok",
      "previewToken",
      "pathId",
      "payloadSha256",
      "expectedRevision",
      "expiresAtMs",
      "requiredConfirm",
      "summary"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.management-work-preview.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "previewToken": {
        "type": "string",
        "minLength": 32
      },
      "pathId": {
        "type": "string",
        "minLength": 1
      },
      "payloadSha256": {
        "type": "string",
        "minLength": 71
      },
      "expectedRevision": {
        "type": "object"
      },
      "expiresAtMs": {
        "type": "integer",
        "minimum": 1
      },
      "requiredConfirm": {
        "type": "string",
        "minLength": 1
      },
      "summary": {
        "type": "object",
        "required": [
          "title",
          "items",
          "risk"
        ],
        "properties": {
          "title": {
            "type": "string",
            "minLength": 1
          },
          "items": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "risk": {
            "type": "string",
            "enum": [
              "R1",
              "R2",
              "R3"
            ]
          }
        }
      }
    }
  },
  "management-work-receipt.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.management-work-receipt.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "ok",
      "receiptId",
      "pathId",
      "payloadSha256",
      "appliedAtMs",
      "auditId",
      "rollbackAvailable",
      "rollbackToken",
      "rollbackAuthority",
      "restartComponents",
      "result"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.management-work-receipt.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "receiptId": {
        "type": "string",
        "minLength": 1
      },
      "pathId": {
        "type": "string",
        "minLength": 1
      },
      "payloadSha256": {
        "type": "string",
        "minLength": 71
      },
      "appliedAtMs": {
        "type": "integer",
        "minimum": 1
      },
      "auditId": {
        "type": "integer",
        "minimum": 1
      },
      "rollbackAvailable": {
        "type": "boolean"
      },
      "rollbackToken": {
        "type": "string"
      },
      "rollbackAuthority": {
        "type": "object"
      },
      "restartComponents": {
        "type": "array",
        "items": {
          "type": "string"
        }
      },
      "result": {
        "type": "object"
      },
      "rollbackOfReceiptId": {
        "type": "string",
        "minLength": 1
      }
    }
  },
  "memory-bootstrap.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.memory-bootstrap.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "bootstrapId",
      "sessionId",
      "project",
      "roleId",
      "generatedAtMs",
      "queryFree",
      "sections",
      "sourceIds",
      "budget",
      "policy"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.memory-bootstrap.v1"
      },
      "bootstrapId": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "project": {
        "type": "string"
      },
      "roleId": {
        "type": "string"
      },
      "generatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "queryFree": {
        "type": "boolean",
        "const": true
      },
      "sections": {
        "type": "object",
        "required": [
          "stablePreferences",
          "projectState",
          "topicBooks",
          "recentTimeline",
          "activeAtoms",
          "oneRing"
        ],
        "properties": {
          "stablePreferences": {
            "type": "array",
            "items": {
              "$ref": "#/$defs/contextSource"
            }
          },
          "projectState": {
            "type": "array",
            "items": {
              "$ref": "#/$defs/contextSource"
            }
          },
          "topicBooks": {
            "type": "array",
            "items": {
              "$ref": "#/$defs/contextSource"
            }
          },
          "recentTimeline": {
            "type": "array",
            "items": {
              "$ref": "#/$defs/contextSource"
            }
          },
          "activeAtoms": {
            "type": "array",
            "items": {
              "$ref": "#/$defs/contextSource"
            }
          },
          "oneRing": {
            "type": "array",
            "items": {
              "$ref": "#/$defs/contextSource"
            }
          }
        }
      },
      "sourceIds": {
        "type": "array",
        "items": {
          "type": "string",
          "minLength": 1
        }
      },
      "budget": {
        "type": "object",
        "required": [
          "maxChars",
          "usedChars",
          "omittedCounts"
        ],
        "properties": {
          "maxChars": {
            "type": "integer",
            "minimum": 1
          },
          "usedChars": {
            "type": "integer",
            "minimum": 0
          },
          "omittedCounts": {
            "type": "object"
          }
        }
      },
      "policy": {
        "type": "object",
        "required": [
          "automaticRecall",
          "lifecycle",
          "oneRingMaySupportFacts",
          "rawDialogueIsLongTermFact"
        ],
        "properties": {
          "automaticRecall": {
            "type": "string",
            "const": "session_start_only"
          },
          "lifecycle": {
            "type": "string",
            "const": "once"
          },
          "oneRingMaySupportFacts": {
            "type": "boolean",
            "const": false
          },
          "rawDialogueIsLongTermFact": {
            "type": "boolean",
            "const": false
          },
          "layerBoundaries": {
            "type": "object",
            "required": [
              "evidence",
              "atom",
              "topicBook",
              "roleBook",
              "timeline"
            ],
            "properties": {
              "evidence": {
                "type": "string"
              },
              "atom": {
                "type": "string"
              },
              "topicBook": {
                "type": "string"
              },
              "roleBook": {
                "type": "string"
              },
              "timeline": {
                "type": "string"
              }
            }
          }
        }
      }
    },
    "$defs": {
      "contextSource": {
        "type": "object",
        "required": [
          "sourceType",
          "sourceId",
          "text",
          "occurredAtMs",
          "maySupportFacts",
          "provenance"
        ],
        "properties": {
          "sourceType": {
            "type": "string",
            "enum": [
              "memory_atom",
              "memory_book",
              "memory_evidence",
              "planning_item"
            ]
          },
          "sourceId": {
            "type": "string",
            "minLength": 1
          },
          "text": {
            "type": "string",
            "minLength": 1
          },
          "kind": {
            "type": "string"
          },
          "occurredAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "maySupportFacts": {
            "type": "boolean"
          },
          "provenance": {
            "type": "object"
          },
          "source": {
            "$ref": "#/$defs/sourceRef"
          },
          "ref": {
            "$ref": "#/$defs/sourceRef"
          }
        }
      },
      "sourceRef": {
        "type": "object",
        "required": [
          "type",
          "id"
        ],
        "properties": {
          "type": {
            "type": "string"
          },
          "id": {
            "type": "string"
          },
          "bookId": {
            "type": "string"
          }
        }
      }
    }
  },
  "memory-catalog.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.memory-catalog.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "project",
      "catalogVersion",
      "items"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.memory-catalog.v1"
      },
      "project": {
        "type": "string",
        "minLength": 1
      },
      "catalogVersion": {
        "type": "string",
        "minLength": 1
      },
      "items": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/item"
        }
      }
    },
    "$defs": {
      "item": {
        "type": "object",
        "required": [
          "bookId",
          "bookKey",
          "bookType",
          "title",
          "summary",
          "updatedAtMs",
          "sourceCount",
          "status"
        ],
        "properties": {
          "bookId": {
            "type": "string",
            "minLength": 1
          },
          "bookKey": {
            "type": "string",
            "minLength": 1
          },
          "bookType": {
            "type": "string",
            "enum": [
              "daily",
              "topic",
              "project",
              "session"
            ]
          },
          "title": {
            "type": "string",
            "minLength": 1
          },
          "summary": {
            "type": "string"
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "sourceCount": {
            "type": "integer",
            "minimum": 0
          },
          "status": {
            "type": "string",
            "enum": [
              "active",
              "archived"
            ]
          }
        }
      }
    }
  },
  "memory-entity.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.memory-entity.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "ok",
      "settingsRevision",
      "runtimeRevision",
      "kind",
      "entityId",
      "entityRevision",
      "project",
      "entity",
      "attributes",
      "connections",
      "members",
      "limits"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.memory-entity.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "settingsRevision": {
        "type": "string",
        "minLength": 1
      },
      "runtimeRevision": {
        "type": "integer",
        "minimum": 0
      },
      "kind": {
        "type": "string",
        "enum": [
          "tag",
          "group",
          "book"
        ]
      },
      "entityId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 128
      },
      "entityRevision": {
        "type": "string",
        "pattern": "^sha256:[0-9a-f]{64}$"
      },
      "project": {
        "type": "string",
        "maxLength": 128
      },
      "entity": {
        "$ref": "#/$defs/node"
      },
      "attributes": {
        "$ref": "#/$defs/attributes"
      },
      "connections": {
        "$ref": "#/$defs/page"
      },
      "members": {
        "$ref": "#/$defs/page"
      },
      "limits": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "connectionsLimit",
          "membersLimit"
        ],
        "properties": {
          "connectionsLimit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100
          },
          "membersLimit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100
          }
        }
      }
    },
    "$defs": {
      "nodeKind": {
        "type": "string",
        "enum": [
          "tag",
          "group",
          "atom",
          "book",
          "phrase",
          "memory"
        ]
      },
      "node": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "id",
          "entityId",
          "kind",
          "label",
          "description",
          "color",
          "status",
          "source",
          "project",
          "qualityScore",
          "memberCount",
          "edgeCount",
          "updatedAtMs"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "entityId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128
          },
          "kind": {
            "$ref": "#/$defs/nodeKind"
          },
          "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120
          },
          "description": {
            "type": "string",
            "maxLength": 240
          },
          "color": {
            "type": "string",
            "enum": [
              "blue",
              "teal",
              "green",
              "orange",
              "pink",
              "purple",
              "gray"
            ]
          },
          "status": {
            "type": "string",
            "minLength": 1,
            "maxLength": 32
          },
          "source": {
            "type": "string",
            "maxLength": 64
          },
          "project": {
            "type": "string",
            "maxLength": 128
          },
          "qualityScore": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "memberCount": {
            "type": "integer",
            "minimum": 0
          },
          "edgeCount": {
            "type": "integer",
            "minimum": 0
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "attributes": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "type",
          "aliases",
          "tags"
        ],
        "properties": {
          "type": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64
          },
          "aliases": {
            "type": "array",
            "maxItems": 64,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 64
            }
          },
          "tags": {
            "type": "array",
            "maxItems": 64,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 64
            }
          }
        }
      },
      "edge": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "id",
          "kind",
          "sourceId",
          "targetId",
          "sourceKind",
          "targetKind",
          "relation",
          "weight",
          "directionBias",
          "evidenceCount",
          "source",
          "updatedAtMs"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512
          },
          "kind": {
            "type": "string",
            "enum": [
              "tagRelation",
              "groupMember",
              "tagMember"
            ]
          },
          "sourceId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "targetId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "sourceKind": {
            "$ref": "#/$defs/nodeKind"
          },
          "targetKind": {
            "$ref": "#/$defs/nodeKind"
          },
          "relation": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64
          },
          "weight": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "directionBias": {
            "type": "number",
            "minimum": -1,
            "maximum": 1
          },
          "evidenceCount": {
            "type": "integer",
            "minimum": 0
          },
          "source": {
            "type": "string",
            "maxLength": 64
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "related": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "node",
          "edge"
        ],
        "properties": {
          "node": {
            "$ref": "#/$defs/node"
          },
          "edge": {
            "$ref": "#/$defs/edge"
          }
        }
      },
      "page": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "items",
          "nextCursor",
          "limit",
          "hasMore"
        ],
        "properties": {
          "items": {
            "type": "array",
            "maxItems": 100,
            "items": {
              "$ref": "#/$defs/related"
            }
          },
          "nextCursor": {
            "type": "string",
            "maxLength": 7
          },
          "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100
          },
          "hasMore": {
            "type": "boolean"
          }
        }
      }
    }
  },
  "memory-governance-preview.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.memory-governance-preview.v1",
    "title": "Memory Governance Preview",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "previewId",
      "proposalId",
      "operation",
      "applyOperation",
      "sessionId",
      "project",
      "targetId",
      "memoryKind",
      "proposedText",
      "reason",
      "evidenceIds",
      "summary",
      "status",
      "reviewRequired",
      "applyOperationAvailable",
      "mutationApplied",
      "writes",
      "audit",
      "createdAtMs",
      "expiresAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.memory-governance-preview.v1"
      },
      "previewId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240
      },
      "proposalId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240
      },
      "operation": {
        "type": "string",
        "enum": [
          "remember_preview",
          "correct_preview",
          "forget_preview"
        ]
      },
      "applyOperation": {
        "type": "string",
        "enum": [
          "remember_apply",
          "correct_apply",
          "forget_apply"
        ]
      },
      "sessionId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240
      },
      "project": {
        "type": "string",
        "maxLength": 200
      },
      "targetId": {
        "type": "string",
        "maxLength": 240
      },
      "memoryKind": {
        "type": "string",
        "enum": [
          "",
          "fact",
          "preference",
          "decision",
          "commitment",
          "project_state"
        ]
      },
      "proposedText": {
        "type": "string",
        "maxLength": 1200
      },
      "reason": {
        "type": "string",
        "maxLength": 400
      },
      "evidenceIds": {
        "type": "array",
        "minItems": 1,
        "maxItems": 16,
        "items": {
          "type": "string",
          "minLength": 1,
          "maxLength": 240
        }
      },
      "summary": {
        "type": "string",
        "minLength": 1,
        "maxLength": 400
      },
      "status": {
        "type": "string",
        "enum": [
          "ready",
          "applied",
          "rolled_back",
          "expired",
          "failed"
        ]
      },
      "reviewRequired": {
        "type": "boolean",
        "const": true
      },
      "applyOperationAvailable": {
        "type": "boolean"
      },
      "mutationApplied": {
        "type": "boolean",
        "const": false
      },
      "writes": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "proposalStored",
          "memoryAtoms",
          "memoryBooks",
          "retrievalVectors"
        ],
        "properties": {
          "proposalStored": {
            "type": "boolean",
            "const": true
          },
          "memoryAtoms": {
            "type": "boolean",
            "const": false
          },
          "memoryBooks": {
            "type": "boolean",
            "const": false
          },
          "retrievalVectors": {
            "type": "boolean",
            "const": false
          }
        }
      },
      "audit": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "payloadSha256",
          "recordKind",
          "sessionId",
          "idempotencyKey"
        ],
        "properties": {
          "payloadSha256": {
            "type": "string",
            "minLength": 64,
            "maxLength": 64
          },
          "recordKind": {
            "type": "string",
            "const": "memory_governance_proposal"
          },
          "sessionId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "idempotencyKey": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          }
        }
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "expiresAtMs": {
        "type": "integer",
        "minimum": 0
      }
    }
  },
  "memory-graph.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.memory-graph.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "ok",
      "settingsRevision",
      "runtimeRevision",
      "graphRevision",
      "plane",
      "project",
      "filters",
      "nodes",
      "edges",
      "truncated",
      "limits"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.memory-graph.v1"
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "settingsRevision": {
        "type": "string",
        "minLength": 1
      },
      "runtimeRevision": {
        "type": "integer",
        "minimum": 0
      },
      "graphRevision": {
        "type": "string",
        "pattern": "^sha256:[0-9a-f]{64}$"
      },
      "plane": {
        "type": "string",
        "enum": [
          "tags",
          "groups"
        ]
      },
      "project": {
        "type": "string",
        "maxLength": 128
      },
      "filters": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "status",
          "query",
          "focusId",
          "minWeight"
        ],
        "properties": {
          "status": {
            "type": "string",
            "enum": [
              "active",
              "merged",
              "all"
            ]
          },
          "query": {
            "type": "string",
            "maxLength": 200
          },
          "focusId": {
            "type": "string",
            "maxLength": 128
          },
          "minWeight": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          }
        }
      },
      "nodes": {
        "type": "array",
        "maxItems": 200,
        "items": {
          "$ref": "#/$defs/node"
        }
      },
      "edges": {
        "type": "array",
        "maxItems": 500,
        "items": {
          "$ref": "#/$defs/edge"
        }
      },
      "truncated": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "nodes",
          "edges"
        ],
        "properties": {
          "nodes": {
            "type": "boolean"
          },
          "edges": {
            "type": "boolean"
          }
        }
      },
      "limits": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "nodeLimit",
          "edgeLimit",
          "depth"
        ],
        "properties": {
          "nodeLimit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 200
          },
          "edgeLimit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500
          },
          "depth": {
            "type": "integer",
            "minimum": 0,
            "maximum": 2
          }
        }
      }
    },
    "$defs": {
      "nodeKind": {
        "type": "string",
        "enum": [
          "tag",
          "group",
          "atom",
          "book",
          "phrase"
        ]
      },
      "node": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "id",
          "entityId",
          "kind",
          "label",
          "description",
          "color",
          "status",
          "source",
          "project",
          "qualityScore",
          "memberCount",
          "edgeCount",
          "updatedAtMs"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "entityId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128
          },
          "kind": {
            "$ref": "#/$defs/nodeKind"
          },
          "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": 120
          },
          "description": {
            "type": "string",
            "maxLength": 240
          },
          "color": {
            "type": "string",
            "enum": [
              "blue",
              "teal",
              "green",
              "orange",
              "pink",
              "purple",
              "gray"
            ]
          },
          "status": {
            "type": "string",
            "minLength": 1,
            "maxLength": 32
          },
          "source": {
            "type": "string",
            "maxLength": 64
          },
          "project": {
            "type": "string",
            "maxLength": 128
          },
          "qualityScore": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "memberCount": {
            "type": "integer",
            "minimum": 0
          },
          "edgeCount": {
            "type": "integer",
            "minimum": 0
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "edge": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "id",
          "kind",
          "sourceId",
          "targetId",
          "sourceKind",
          "targetKind",
          "relation",
          "weight",
          "directionBias",
          "evidenceCount",
          "source",
          "updatedAtMs"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 512
          },
          "kind": {
            "type": "string",
            "enum": [
              "tagRelation",
              "groupMember"
            ]
          },
          "sourceId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "targetId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 160
          },
          "sourceKind": {
            "$ref": "#/$defs/nodeKind"
          },
          "targetKind": {
            "$ref": "#/$defs/nodeKind"
          },
          "relation": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64
          },
          "weight": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "directionBias": {
            "type": "number",
            "minimum": -1,
            "maximum": 1
          },
          "evidenceCount": {
            "type": "integer",
            "minimum": 0
          },
          "source": {
            "type": "string",
            "maxLength": 64
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      }
    }
  },
  "memory-read-error.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.memory-read-error.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "ok",
      "errorCode",
      "error"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.memory-read-error.v1"
      },
      "ok": {
        "type": "boolean",
        "const": false
      },
      "errorCode": {
        "type": "string",
        "const": "invalid_request"
      },
      "error": {
        "type": "string",
        "minLength": 1,
        "maxLength": 256
      }
    }
  },
  "memory-reference.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.memory-reference.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "settingsRevision",
      "runtimeRevision",
      "ok",
      "kind",
      "referenceId",
      "item",
      "source",
      "ref",
      "evidenceRefs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.memory-reference.v1"
      },
      "settingsRevision": {
        "type": "string",
        "minLength": 1
      },
      "runtimeRevision": {
        "type": "integer",
        "minimum": 0
      },
      "ok": {
        "type": "boolean",
        "const": true
      },
      "kind": {
        "$ref": "#/$defs/referenceKind"
      },
      "referenceId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240
      },
      "item": {
        "type": "object",
        "required": [
          "id",
          "title",
          "status"
        ],
        "properties": {
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "title": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "status": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64
          },
          "text": {
            "type": "string",
            "maxLength": 32000
          },
          "textPreview": {
            "type": "string",
            "maxLength": 2000
          },
          "summary": {
            "type": "string",
            "maxLength": 2000
          },
          "detail": {
            "type": "string",
            "maxLength": 2000
          },
          "sensitive": {
            "type": "boolean"
          },
          "ownerKind": {
            "type": "string",
            "maxLength": 32
          },
          "ownerId": {
            "type": "string",
            "maxLength": 240
          },
          "createdAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "updatedAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "occurredAtMs": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "source": {
        "$ref": "#/$defs/source"
      },
      "ref": {
        "$ref": "#/$defs/reference"
      },
      "evidenceRefs": {
        "type": "array",
        "maxItems": 80,
        "items": {
          "$ref": "#/$defs/reference"
        }
      }
    },
    "$defs": {
      "referenceKind": {
        "type": "string",
        "enum": [
          "event",
          "evidence",
          "atom",
          "book",
          "timeline",
          "role_book_revision"
        ]
      },
      "source": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "kind",
          "id"
        ],
        "properties": {
          "kind": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80
          },
          "sourceKind": {
            "type": "string",
            "maxLength": 120
          },
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 320
          }
        }
      },
      "reference": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "kind",
          "id",
          "referenceKind",
          "referenceId"
        ],
        "properties": {
          "kind": {
            "$ref": "#/$defs/referenceKind"
          },
          "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "referenceKind": {
            "$ref": "#/$defs/referenceKind"
          },
          "referenceId": {
            "type": "string",
            "minLength": 1,
            "maxLength": 240
          },
          "label": {
            "type": "string",
            "maxLength": 180
          }
        }
      }
    }
  },
  "observation-event.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.observation-event.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "eventType",
      "eventId",
      "sequence",
      "resumeToken",
      "traceId",
      "spanId",
      "parentSpanId",
      "sessionId",
      "roomId",
      "turnId",
      "runId",
      "category",
      "phase",
      "name",
      "status",
      "summary",
      "createdAtMs",
      "startedAtMs",
      "endedAtMs",
      "durationMs",
      "privacyClass",
      "metrics",
      "attributes",
      "refs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.observation-event.v1"
      },
      "eventType": {
        "type": "string",
        "enum": [
          "observation",
          "snapshot_required"
        ]
      },
      "eventId": {
        "type": "string",
        "minLength": 1
      },
      "sequence": {
        "type": "integer",
        "minimum": 0
      },
      "resumeToken": {
        "type": "string",
        "minLength": 1
      },
      "traceId": {
        "type": "string",
        "minLength": 1
      },
      "spanId": {
        "type": "string",
        "minLength": 1
      },
      "parentSpanId": {
        "type": "string"
      },
      "sessionId": {
        "type": "string"
      },
      "roomId": {
        "type": "string"
      },
      "turnId": {
        "type": "string"
      },
      "runId": {
        "type": "string"
      },
      "category": {
        "type": "string",
        "enum": [
          "context",
          "retrieval",
          "memory",
          "tool",
          "agent",
          "room",
          "intercom",
          "approval",
          "runtime",
          "system"
        ]
      },
      "phase": {
        "type": "string",
        "minLength": 1
      },
      "name": {
        "type": "string",
        "minLength": 1
      },
      "status": {
        "type": "string",
        "enum": [
          "queued",
          "running",
          "waiting",
          "completed",
          "failed",
          "cancelled",
          "info"
        ]
      },
      "summary": {
        "type": "string"
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "startedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "endedAtMs": {
        "type": [
          "integer",
          "null"
        ],
        "minimum": 0
      },
      "durationMs": {
        "type": [
          "number",
          "null"
        ],
        "minimum": 0
      },
      "privacyClass": {
        "type": "string",
        "enum": [
          "metadata",
          "redacted",
          "owner_local"
        ]
      },
      "metrics": {
        "type": "object"
      },
      "attributes": {
        "type": "object"
      },
      "refs": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "kind",
            "id",
            "label"
          ],
          "properties": {
            "kind": {
              "type": "string",
              "minLength": 1
            },
            "id": {
              "type": "string",
              "minLength": 1
            },
            "label": {
              "type": "string"
            }
          }
        }
      }
    }
  },
  "observation-snapshot.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.observation-snapshot.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "generatedAtMs",
      "firstSequence",
      "lastSequence",
      "resumeToken",
      "truncated",
      "filters",
      "counts",
      "items"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.observation-snapshot.v1"
      },
      "generatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "firstSequence": {
        "type": "integer",
        "minimum": 0
      },
      "lastSequence": {
        "type": "integer",
        "minimum": 0
      },
      "resumeToken": {
        "type": "string",
        "minLength": 1
      },
      "truncated": {
        "type": "boolean"
      },
      "filters": {
        "type": "object"
      },
      "counts": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "total",
          "byCategory",
          "byStatus"
        ],
        "properties": {
          "total": {
            "type": "integer",
            "minimum": 0
          },
          "byCategory": {
            "type": "object"
          },
          "byStatus": {
            "type": "object"
          }
        }
      },
      "items": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/event"
        }
      }
    },
    "$defs": {
      "event": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "schemaVersion",
          "eventType",
          "eventId",
          "sequence",
          "resumeToken",
          "traceId",
          "spanId",
          "parentSpanId",
          "sessionId",
          "roomId",
          "turnId",
          "runId",
          "category",
          "phase",
          "name",
          "status",
          "summary",
          "createdAtMs",
          "startedAtMs",
          "endedAtMs",
          "durationMs",
          "privacyClass",
          "metrics",
          "attributes",
          "refs"
        ],
        "properties": {
          "schemaVersion": {
            "type": "string",
            "const": "rag-ime.observation-event.v1"
          },
          "eventType": {
            "type": "string",
            "enum": [
              "observation",
              "snapshot_required"
            ]
          },
          "eventId": {
            "type": "string",
            "minLength": 1
          },
          "sequence": {
            "type": "integer",
            "minimum": 0
          },
          "resumeToken": {
            "type": "string",
            "minLength": 1
          },
          "traceId": {
            "type": "string",
            "minLength": 1
          },
          "spanId": {
            "type": "string",
            "minLength": 1
          },
          "parentSpanId": {
            "type": "string"
          },
          "sessionId": {
            "type": "string"
          },
          "roomId": {
            "type": "string"
          },
          "turnId": {
            "type": "string"
          },
          "runId": {
            "type": "string"
          },
          "category": {
            "type": "string",
            "enum": [
              "context",
              "retrieval",
              "memory",
              "tool",
              "agent",
              "room",
              "intercom",
              "approval",
              "runtime",
              "system"
            ]
          },
          "phase": {
            "type": "string",
            "minLength": 1
          },
          "name": {
            "type": "string",
            "minLength": 1
          },
          "status": {
            "type": "string",
            "enum": [
              "queued",
              "running",
              "waiting",
              "completed",
              "failed",
              "cancelled",
              "info"
            ]
          },
          "summary": {
            "type": "string"
          },
          "createdAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "startedAtMs": {
            "type": "integer",
            "minimum": 0
          },
          "endedAtMs": {
            "type": [
              "integer",
              "null"
            ],
            "minimum": 0
          },
          "durationMs": {
            "type": [
              "number",
              "null"
            ],
            "minimum": 0
          },
          "privacyClass": {
            "type": "string",
            "enum": [
              "metadata",
              "redacted",
              "owner_local"
            ]
          },
          "metrics": {
            "type": "object"
          },
          "attributes": {
            "type": "object"
          },
          "refs": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "kind",
                "id",
                "label"
              ],
              "properties": {
                "kind": {
                  "type": "string",
                  "minLength": 1
                },
                "id": {
                  "type": "string",
                  "minLength": 1
                },
                "label": {
                  "type": "string"
                }
              }
            }
          }
        }
      }
    }
  },
  "overlay-config.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.overlay-config.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "candidateFontSize",
      "maxWidth",
      "fadeAnimation",
      "panelStyle",
      "expiresAfterMs",
      "maxCandidates",
      "showSourceBadge",
      "badges",
      "colors",
      "keyPolicy",
      "activeRag"
    ],
    "properties": {
      "schemaVersion": {
        "const": "rag-ime.overlay-config.v1"
      },
      "candidateFontSize": {
        "type": "integer",
        "minimum": 11,
        "maximum": 24
      },
      "maxWidth": {
        "type": "integer",
        "minimum": 320,
        "maximum": 760
      },
      "fadeAnimation": {
        "type": "boolean"
      },
      "panelStyle": {
        "type": "string",
        "enum": [
          "compact",
          "expanded"
        ]
      },
      "expiresAfterMs": {
        "type": "integer",
        "minimum": 0,
        "maximum": 15000
      },
      "maxCandidates": {
        "type": "integer",
        "minimum": 1,
        "maximum": 10
      },
      "showSourceBadge": {
        "type": "boolean"
      },
      "badges": {
        "type": "object",
        "additionalProperties": {
          "type": "string"
        }
      },
      "colors": {
        "type": "object",
        "additionalProperties": {
          "type": "string"
        }
      },
      "keyPolicy": {
        "type": "object"
      },
      "activeRag": {
        "type": "object",
        "required": [
          "enabled",
          "shortcut"
        ],
        "properties": {
          "enabled": {
            "type": "boolean"
          },
          "shortcut": {
            "type": "string",
            "minLength": 1
          }
        }
      }
    }
  },
  "pi-runtime-manifest.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.pi-runtime-manifest.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "runtimeVersion",
      "piVersion",
      "platform",
      "architecture",
      "launchKind",
      "piEntrypoint",
      "extensionEntrypoint",
      "tools",
      "createdAtMs",
      "source",
      "files"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.pi-runtime-manifest.v1"
      },
      "runtimeVersion": {
        "type": "string",
        "minLength": 1
      },
      "piVersion": {
        "type": "string",
        "minLength": 1
      },
      "runtimeProtocolVersion": {
        "type": "string",
        "enum": [
          "1",
          "2"
        ]
      },
      "platform": {
        "type": "string",
        "minLength": 1
      },
      "architecture": {
        "type": "string",
        "minLength": 1
      },
      "launchKind": {
        "type": "string",
        "enum": [
          "node",
          "standalone"
        ]
      },
      "piEntrypoint": {
        "type": "string",
        "minLength": 1
      },
      "nodeEntrypoint": {
        "type": "string"
      },
      "extensionEntrypoint": {
        "type": "string",
        "minLength": 1
      },
      "tools": {
        "type": "array",
        "items": {
          "type": "string",
          "minLength": 1
        }
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "source": {
        "type": "object",
        "required": [
          "repository",
          "commit",
          "package"
        ],
        "properties": {
          "repository": {
            "type": "string",
            "minLength": 1
          },
          "commit": {
            "type": "string",
            "minLength": 1
          },
          "package": {
            "type": "string",
            "minLength": 1
          }
        }
      },
      "files": {
        "type": "array",
        "items": {
          "type": "object",
          "required": [
            "path",
            "sha256",
            "byteSize",
            "executable"
          ],
          "properties": {
            "path": {
              "type": "string",
              "minLength": 1
            },
            "sha256": {
              "type": "string",
              "minLength": 64
            },
            "byteSize": {
              "type": "integer",
              "minimum": 0
            },
            "executable": {
              "type": "boolean"
            }
          }
        }
      }
    }
  },
  "rime-rank-selection.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.rime-rank-selection.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "selectionId",
      "sourceType",
      "preedit",
      "acceptedText",
      "candidateRank"
    ],
    "properties": {
      "schemaVersion": {
        "const": "rag-ime.rime-rank-selection.v1"
      },
      "selectionId": {
        "type": "string",
        "minLength": 1,
        "maxLength": 160
      },
      "sourceType": {
        "const": "rime"
      },
      "selectionSource": {
        "type": "string",
        "maxLength": 80
      },
      "preedit": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240
      },
      "acceptedText": {
        "type": "string",
        "minLength": 1,
        "maxLength": 240
      },
      "rejectedText": {
        "type": "string",
        "maxLength": 240
      },
      "candidateRank": {
        "type": "integer",
        "minimum": 1,
        "maximum": 999
      },
      "shownCandidateCount": {
        "type": "integer",
        "minimum": 0,
        "maximum": 999
      },
      "app": {
        "type": "string",
        "maxLength": 240
      },
      "frontAppBundleId": {
        "type": "string",
        "maxLength": 240
      },
      "frontmostApp": {
        "type": "string",
        "maxLength": 240
      },
      "bundleId": {
        "type": "string",
        "maxLength": 240
      },
      "project": {
        "type": "string",
        "maxLength": 240
      },
      "privacyDisposition": {
        "type": "string",
        "enum": [
          "allowed",
          "sensitive",
          "unknown"
        ]
      },
      "sensitiveField": {
        "type": "boolean"
      },
      "secureInput": {
        "type": "boolean"
      },
      "dryRun": {
        "type": "boolean"
      }
    },
    "additionalProperties": false
  },
  "rime-select.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.rime-select.v1",
    "type": "object",
    "required": [
      "candidate"
    ],
    "properties": {
      "candidate": {
        "$ref": "#/$defs/candidate"
      },
      "shownCandidates": {
        "type": "array",
        "items": {
          "$ref": "#/$defs/candidate"
        }
      },
      "query": {
        "type": "string"
      },
      "recentContext": {
        "type": "string"
      },
      "committedContext": {
        "type": "string"
      },
      "preedit": {
        "type": "string"
      },
      "project": {
        "type": "string"
      },
      "app": {
        "type": "string"
      },
      "frontAppBundleId": {
        "type": "string"
      },
      "frontmostApp": {
        "type": "string"
      },
      "bundleId": {
        "type": "string"
      },
      "contextGroupId": {
        "type": "string"
      },
      "contextGroupLevel": {
        "type": "string"
      },
      "privacyDisposition": {
        "type": "string",
        "enum": [
          "allowed",
          "sensitive",
          "unknown"
        ]
      },
      "sensitiveField": {
        "type": "boolean"
      },
      "secureInput": {
        "type": "boolean"
      },
      "dryRun": {
        "type": "boolean"
      }
    },
    "$defs": {
      "candidate": {
        "type": "object",
        "required": [
          "insertText",
          "sourceType"
        ],
        "properties": {
          "text": {
            "type": "string"
          },
          "insertText": {
            "type": "string",
            "minLength": 1
          },
          "sourceType": {
            "type": "string"
          },
          "memoryId": {
            "type": "string"
          },
          "suggestionId": {
            "type": "string"
          },
          "sourceEventId": {
            "type": [
              "integer",
              "null"
            ]
          }
        }
      }
    }
  },
  "rime-suggest-request.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.rime-suggest-request.v1",
    "type": "object",
    "required": [
      "sessionId",
      "requestSeq"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string"
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "requestSeq": {
        "type": "integer",
        "minimum": 0
      },
      "rawInput": {
        "type": "string"
      },
      "preedit": {
        "type": "string"
      },
      "commitTextPreview": {
        "type": "string"
      },
      "committedContext": {
        "type": "string"
      },
      "project": {
        "type": "string"
      },
      "app": {
        "type": "string"
      },
      "privacyDisposition": {
        "type": "string",
        "enum": [
          "allowed",
          "sensitive",
          "unknown"
        ]
      },
      "privacyLeaseId": {
        "type": "string"
      },
      "privacyLeaseEpoch": {
        "type": "integer",
        "minimum": 0
      },
      "privacyFocusEpoch": {
        "type": "integer",
        "minimum": 0
      },
      "sensitiveField": {
        "type": "boolean"
      },
      "secureInput": {
        "type": "boolean"
      },
      "progressiveFollowUp": {
        "type": "boolean"
      },
      "frontendRevision": {
        "type": "integer",
        "minimum": 0
      },
      "selectionEpoch": {
        "type": "integer",
        "minimum": 0
      },
      "inputGeneration": {
        "type": "integer",
        "minimum": 0
      },
      "foregroundText": {
        "$ref": "#/$defs/foregroundContext"
      }
    },
    "$defs": {
      "foregroundContext": {
        "type": "object",
        "required": [
          "available",
          "source",
          "freshnessMs"
        ],
        "properties": {
          "available": {
            "type": "boolean"
          },
          "source": {
            "type": "string"
          },
          "freshnessMs": {
            "type": "integer",
            "minimum": 0
          },
          "surroundingBefore": {
            "type": "string"
          },
          "surroundingAfter": {
            "type": "string"
          },
          "selectedText": {
            "type": "string"
          },
          "canReplaceSelection": {
            "type": "boolean"
          },
          "contextGroupId": {
            "type": "string"
          },
          "contextGroupLevel": {
            "type": "string",
            "enum": [
              "document",
              "project",
              "app",
              "global",
              ""
            ]
          }
        }
      }
    }
  },
  "rime-suggest-response.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.rime-suggest-response.v1",
    "type": "object",
    "required": [
      "schemaVersion",
      "sessionId",
      "requestSeq",
      "displayCandidates",
      "predictionSession",
      "keyPolicy",
      "assistantOverlay"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "requestSeq": {
        "type": "integer",
        "minimum": 0
      },
      "runtimeRevision": {
        "type": "integer",
        "minimum": 0
      },
      "runtimeConfig": {
        "type": "object"
      },
      "displayCandidates": {
        "type": "array"
      },
      "predictionSession": {
        "type": "object"
      },
      "keyPolicy": {
        "type": "object"
      },
      "assistantOverlay": {
        "type": "object"
      },
      "overlayConfig": {
        "type": "object"
      },
      "frontendTransaction": {
        "type": "object"
      },
      "stored": {
        "type": "boolean"
      },
      "noStore": {
        "type": "boolean"
      },
      "privacyAssessment": {
        "type": "object"
      },
      "storageReceipt": {
        "type": "object"
      }
    }
  },
  "role-book-curation.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.role-book-curation.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "traitProposals",
      "capabilityProposals",
      "lessonProposals",
      "commitmentProposals",
      "warnings"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.role-book-curation.v1"
      },
      "traitProposals": {
        "type": "array",
        "maxItems": 6,
        "items": {
          "$ref": "#/$defs/proposal"
        }
      },
      "capabilityProposals": {
        "type": "array",
        "maxItems": 12,
        "items": {
          "$ref": "#/$defs/proposal"
        }
      },
      "lessonProposals": {
        "type": "array",
        "maxItems": 8,
        "items": {
          "$ref": "#/$defs/proposal"
        }
      },
      "commitmentProposals": {
        "type": "array",
        "maxItems": 8,
        "items": {
          "$ref": "#/$defs/proposal"
        }
      },
      "warnings": {
        "type": "array",
        "maxItems": 16,
        "items": {
          "type": "string",
          "maxLength": 240
        }
      }
    },
    "$defs": {
      "proposal": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "text",
          "confidence",
          "sourceEvidenceIds",
          "reviewRequired"
        ],
        "properties": {
          "text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 280
          },
          "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "sourceEvidenceIds": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "uniqueItems": true,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 240
            }
          },
          "reviewRequired": {
            "type": "boolean",
            "const": true
          }
        }
      }
    }
  },
  "role-book-revision-draft.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.role-book-revision-draft.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "draftId",
      "status",
      "project",
      "roleId",
      "baseRoleVersion",
      "sourceDigestId",
      "sourceEvidenceIds",
      "patch",
      "policy",
      "proposalDiagnostics",
      "createdAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.role-book-revision-draft.v1"
      },
      "draftId": {
        "type": "string",
        "minLength": 1
      },
      "status": {
        "type": "string",
        "const": "draft"
      },
      "project": {
        "type": "string"
      },
      "roleId": {
        "type": "string",
        "minLength": 1
      },
      "baseRoleVersion": {
        "type": "string",
        "minLength": 1
      },
      "sourceDigestId": {
        "type": "string",
        "minLength": 1
      },
      "sourceEvidenceIds": {
        "type": "array",
        "items": {
          "type": "string",
          "minLength": 1
        }
      },
      "patch": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "recentWork",
          "traitProposals",
          "capabilityProposals",
          "lessonProposals",
          "commitmentProposals"
        ],
        "properties": {
          "recentWork": {
            "type": "array",
            "items": {
              "type": "object"
            }
          },
          "traitProposals": {
            "type": "array",
            "maxItems": 6,
            "items": {
              "$ref": "#/$defs/proposal"
            }
          },
          "capabilityProposals": {
            "type": "array",
            "maxItems": 12,
            "items": {
              "$ref": "#/$defs/proposal"
            }
          },
          "lessonProposals": {
            "type": "array",
            "maxItems": 8,
            "items": {
              "$ref": "#/$defs/proposal"
            }
          },
          "commitmentProposals": {
            "type": "array",
            "maxItems": 8,
            "items": {
              "$ref": "#/$defs/proposal"
            }
          }
        }
      },
      "policy": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "defaultApply",
          "safeAutoApplyFields",
          "reviewRequiredFields"
        ],
        "properties": {
          "defaultApply": {
            "type": "boolean",
            "const": false
          },
          "safeAutoApplyFields": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": [
                "recentWork"
              ]
            }
          },
          "reviewRequiredFields": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": [
                "traits",
                "capabilities",
                "lessonsAndLimits",
                "activeCommitments"
              ]
            }
          }
        }
      },
      "proposalDiagnostics": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "status",
          "provider",
          "inputChars",
          "acceptedProposalCount",
          "rejectedProposalCount"
        ],
        "properties": {
          "status": {
            "type": "string",
            "enum": [
              "not_configured",
              "no_conversation_evidence",
              "unsupported",
              "completed",
              "failed"
            ]
          },
          "provider": {
            "type": "string",
            "maxLength": 80
          },
          "inputChars": {
            "type": "integer",
            "minimum": 0,
            "maximum": 12000
          },
          "acceptedProposalCount": {
            "type": "integer",
            "minimum": 0
          },
          "rejectedProposalCount": {
            "type": "integer",
            "minimum": 0
          },
          "error": {
            "type": "string",
            "maxLength": 400
          }
        }
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      }
    },
    "$defs": {
      "proposal": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "text",
          "confidence",
          "sourceEvidenceIds",
          "reviewRequired"
        ],
        "properties": {
          "text": {
            "type": "string",
            "minLength": 1,
            "maxLength": 280
          },
          "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "sourceEvidenceIds": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "uniqueItems": true,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 240
            }
          },
          "reviewRequired": {
            "type": "boolean",
            "const": true
          }
        }
      }
    }
  },
  "session-memory-recall.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.session-memory-recall.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "recallId",
      "sessionId",
      "project",
      "roleId",
      "generatedAtMs",
      "trigger",
      "query",
      "retrieval",
      "items",
      "sourceIds",
      "budget",
      "policy"
    ],
    "properties": {
      "schemaVersion": {
        "const": "rag-ime.session-memory-recall.v1"
      },
      "recallId": {
        "type": "string",
        "minLength": 1
      },
      "sessionId": {
        "type": "string",
        "minLength": 1
      },
      "project": {
        "type": "string"
      },
      "roleId": {
        "type": "string"
      },
      "generatedAtMs": {
        "type": "integer",
        "minimum": 0
      },
      "trigger": {
        "const": "first_user_prompt"
      },
      "query": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "preview",
          "sha256",
          "recentCompleteInputCount",
          "recentCompleteInputUsedForRetrieval"
        ],
        "properties": {
          "preview": {
            "type": "string"
          },
          "sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$"
          },
          "recentCompleteInputCount": {
            "type": "integer",
            "minimum": 0
          },
          "recentCompleteInputUsedForRetrieval": {
            "type": "boolean"
          }
        }
      },
      "retrieval": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "strategy",
          "primaryQuery",
          "matchedAliases",
          "activatedTags",
          "visibleOwners",
          "requestedEmbeddingProvider",
          "embeddingProvider",
          "embeddingFallback",
          "temporalIntent",
          "activityTimelineIncluded"
        ],
        "properties": {
          "strategy": {
            "const": "vcp_hybrid_book_atom"
          },
          "primaryQuery": {
            "type": "string"
          },
          "matchedAliases": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "activatedTags": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "visibleOwners": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": [
                "ownerKind",
                "ownerId"
              ],
              "properties": {
                "ownerKind": {
                  "type": "string"
                },
                "ownerId": {
                  "type": "string",
                  "minLength": 1
                }
              }
            }
          },
          "requestedEmbeddingProvider": {
            "type": "string"
          },
          "embeddingProvider": {
            "type": "string"
          },
          "embeddingFallback": {
            "type": "boolean"
          },
          "temporalIntent": {
            "type": "boolean"
          },
          "activityTimelineIncluded": {
            "type": "boolean"
          }
        }
      },
      "items": {
        "type": "array",
        "maxItems": 12,
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "rank",
            "sourceType",
            "sourceId",
            "title",
            "text",
            "score",
            "confidence",
            "lanes",
            "rawScores",
            "tags",
            "ownerKind",
            "ownerId",
            "evidenceEventIds"
          ],
          "properties": {
            "rank": {
              "type": "integer",
              "minimum": 1
            },
            "sourceType": {
              "enum": [
                "memory_book",
                "memory_atom"
              ]
            },
            "sourceId": {
              "type": "string",
              "minLength": 1
            },
            "title": {
              "type": "string"
            },
            "text": {
              "type": "string",
              "minLength": 1
            },
            "score": {
              "type": "number"
            },
            "confidence": {
              "type": "number",
              "minimum": 0,
              "maximum": 1
            },
            "lanes": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "rawScores": {
              "type": "object",
              "additionalProperties": {
                "type": "number"
              }
            },
            "tags": {
              "type": "array",
              "items": {
                "type": "string"
              }
            },
            "ownerKind": {
              "type": "string"
            },
            "ownerId": {
              "type": "string"
            },
            "evidenceEventIds": {
              "type": "array",
              "items": {
                "type": "integer",
                "minimum": 1
              }
            }
          }
        }
      },
      "sourceIds": {
        "type": "array",
        "items": {
          "type": "string",
          "minLength": 1
        }
      },
      "budget": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "maxItems",
          "maxChars",
          "usedChars",
          "omittedCount"
        ],
        "properties": {
          "maxItems": {
            "type": "integer",
            "minimum": 1
          },
          "maxChars": {
            "type": "integer",
            "minimum": 1
          },
          "usedChars": {
            "type": "integer",
            "minimum": 0
          },
          "omittedCount": {
            "type": "integer",
            "minimum": 0
          }
        }
      },
      "policy": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "priority",
          "lifecycle",
          "evidenceOnly",
          "currentUserMessageWins",
          "rawRecentInputInjected"
        ],
        "properties": {
          "priority": {
            "const": "developer"
          },
          "lifecycle": {
            "const": "session"
          },
          "evidenceOnly": {
            "const": true
          },
          "currentUserMessageWins": {
            "const": true
          },
          "rawRecentInputInjected": {
            "const": false
          }
        }
      }
    }
  },
  "user-memory-draft.v1": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "rag-ime.contract.user-memory-draft.v1",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schemaVersion",
      "draftId",
      "status",
      "project",
      "roleId",
      "sourceDigestId",
      "sourceEvidenceIds",
      "candidates",
      "policy",
      "createdAtMs"
    ],
    "properties": {
      "schemaVersion": {
        "type": "string",
        "const": "rag-ime.user-memory-draft.v1"
      },
      "draftId": {
        "type": "string",
        "minLength": 1
      },
      "status": {
        "type": "string",
        "const": "review_required"
      },
      "project": {
        "type": "string"
      },
      "roleId": {
        "type": "string",
        "minLength": 1
      },
      "sourceDigestId": {
        "type": "string",
        "minLength": 1
      },
      "sourceEvidenceIds": {
        "type": "array",
        "items": {
          "type": "string",
          "minLength": 1
        }
      },
      "candidates": {
        "type": "array",
        "items": {
          "type": "object"
        }
      },
      "policy": {
        "type": "object",
        "required": [
          "rawDialoguePromotion",
          "defaultApply"
        ],
        "properties": {
          "rawDialoguePromotion": {
            "type": "string",
            "const": "forbidden"
          },
          "defaultApply": {
            "type": "boolean",
            "const": false
          }
        }
      },
      "createdAtMs": {
        "type": "integer",
        "minimum": 0
      }
    }
  },
} as const;

export type ContractName = keyof typeof contractSchemas;

export const contractSchemaIds = Object.fromEntries(
  Object.entries(contractSchemas).map(([name, schema]) => [name, schema.$id]),
) as Record<ContractName, string>;
