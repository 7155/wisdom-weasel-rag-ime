/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-skill-policy.v1.json
 */

export interface RoomSkillPolicyV1 {
  schemaVersion: 'wisdom-weasel.room-skill-policy.v1';
  policyId: string;
  version: number;
  hashRule: 'sha256-skill-body-utf8-v1';
  skills: {
    skillId: string;
    stages: string[];
    risk: 'low' | 'medium' | 'high';
    nextCandidates: string[];
  }[];
}
