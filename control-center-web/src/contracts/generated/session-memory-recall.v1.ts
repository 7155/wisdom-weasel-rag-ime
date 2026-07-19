/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/session-memory-recall.v1.json
 */

export interface SessionMemoryRecallV1 {
  schemaVersion: 'rag-ime.session-memory-recall.v1';
  recallId: string;
  sessionId: string;
  project: string;
  roleId: string;
  generatedAtMs: number;
  trigger: 'first_user_prompt' | 'compaction' | 'room_task' | 'subagent_task';
  query: {
    preview: string;
    sha256: string;
    recentCompleteInputCount: number;
    recentCompleteInputUsedForRetrieval: boolean;
    retrievalContextUsed: boolean;
    recentConversationCount: number;
  };
  retrieval: {
    strategy: 'vcp_hybrid_book_atom';
    primaryQuery: string;
    matchedAliases: string[];
    activatedTags: string[];
    visibleOwners: {
      ownerKind: string;
      ownerId: string;
    }[];
    requestedEmbeddingProvider: string;
    embeddingProvider: string;
    embeddingFallback: boolean;
    temporalIntent: boolean;
    activityTimelineIncluded: boolean;
    vectorFusion: {
      applied: boolean;
      queryWeight: number;
      contextWeight: number;
    };
  };
  /**
   * @maxItems 12
   */
  items:
    | []
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ]
    | [
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
        {
          rank: number;
          sourceType: 'memory_book' | 'memory_atom';
          sourceId: string;
          title: string;
          text: string;
          score: number;
          confidence: number;
          lanes: string[];
          rawScores: {
            [k: string]: number;
          };
          tags: string[];
          ownerKind: string;
          ownerId: string;
          evidenceEventIds: number[];
        },
      ];
  /**
   * @maxItems 8
   */
  recentConversation?:
    | []
    | [
        {
          role: 'user' | 'assistant';
          text: string;
        },
      ]
    | [
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
      ]
    | [
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
      ]
    | [
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
      ]
    | [
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
      ]
    | [
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
      ]
    | [
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
      ]
    | [
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
        {
          role: 'user' | 'assistant';
          text: string;
        },
      ];
  /**
   * @maxItems 8
   */
  plan?:
    | []
    | [
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
      ]
    | [
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
      ]
    | [
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
      ]
    | [
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
      ]
    | [
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
      ]
    | [
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
      ]
    | [
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
      ]
    | [
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
        {
          status: 'pending' | 'in_progress';
          title: string;
        },
      ];
  task?: {
    kind?: string;
    objective?: string;
    expectedOutput?: string;
    state?: string;
    /**
     * @maxItems 8
     */
    acceptanceCriteria?:
      | []
      | [string]
      | [string, string]
      | [string, string, string]
      | [string, string, string, string]
      | [string, string, string, string, string]
      | [string, string, string, string, string, string]
      | [string, string, string, string, string, string, string]
      | [string, string, string, string, string, string, string, string];
  };
  sourceIds: string[];
  budget: {
    maxItems: number;
    maxChars: number;
    usedChars: number;
    omittedCount: number;
  };
  policy: {
    priority: 'developer';
    lifecycle: 'session';
    evidenceOnly: true;
    currentUserMessageWins: true;
    rawRecentInputInjected: false;
    recentConversationInjected: boolean;
  };
}
