/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/room-skill-selection.v1.json
 */

export interface RoomSkillSelectionV1 {
  schemaVersion: 'wisdom-weasel.room-skill-selection.v1';
  stage: string;
  selection: 'required' | 'suggested' | 'none';
  skillId: string | null;
  candidateSkillIds: string[];
  risk: string | null;
}
