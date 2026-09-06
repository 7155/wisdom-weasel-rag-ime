import { describe, expect, it } from 'vitest';
import { previewEvalLabRuns } from '@/app/preview-eval-lab-data';
import type { EvalLabExperiment } from './api';
import { compileExperimentDispatch, defaultExperimentSetup } from './execution-contract';
import { ENTERPRISE_RAG_RECIPE_EXPERIMENT_ID, ENTERPRISE_RAG_SCENE_ID, type SceneRecipeBinding } from './scene-recipes';

const experiment = (previewEvalLabRuns().experiments as EvalLabExperiment[])[0]!;
const setup = () => ({
  ...defaultExperimentSetup(experiment),
  goal: 'Improve supported answers while preserving every quality gate',
  allowedChanges: 'Prompt and retrieval configuration only',
  maxCandidates: 3,
  budgetUsd: 2.5,
  stopCondition: 'Stop after the first accepted improvement or two neutral candidates',
  workspaceRoot: '/tmp/paw-candidates',
});

describe('compileExperimentDispatch', () => {
  it('allows a model-only configuration trial while freezing the Judge and other factors', () => {
    const result = compileExperimentDispatch(experiment, { ...setup(), target: 'model' });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.contract.repairOperators.map((operator) => operator.id)).toEqual(['model_configuration']);
    expect(result.contract.counterfactualProbes[0]?.frozenControls).toContain('judge_model');
    expect(result.contract.counterfactualProbes[0]?.hypothesis).toContain('成本');
    expect(compileExperimentDispatch(experiment, { ...setup(), target: 'model', layer: 'implementation' }).ok).toBe(false);
  });
  it('exposes an explicit optimization target and keeps only target-specific operators', () => {
    const prompt = compileExperimentDispatch(experiment, setup());
    expect(prompt.ok).toBe(true);
    if (!prompt.ok) return;
    expect(prompt.contract.scope.target).toBe('prompt');
    expect(prompt.contract.repairOperators.map((operator) => operator.id)).toEqual(['prompt_evidence_gate']);
    expect(prompt.contract.counterfactualProbes[0]?.operatorId).toBe('prompt_evidence_gate');

    const tool = compileExperimentDispatch(experiment, { ...setup(), target: 'tool' });
    expect(tool.ok).toBe(true);
    if (!tool.ok) return;
    expect(tool.contract.repairOperators.map((operator) => operator.id)).toEqual(['tool_configuration']);
    expect(tool.contract.repairOperators[0]?.failureOwner).toBe('tool_runtime');

    const skill = compileExperimentDispatch(experiment, { ...setup(), target: 'skill', layer: 'implementation' });
    expect(skill.ok).toBe(true);
    if (!skill.ok) return;
    expect(skill.contract.repairOperators.map((operator) => operator.id)).toEqual(['skill_implementation']);
    expect(skill.contract.repairOperators[0]?.failureOwner).toBe('skill_runtime');
  });

  it('freezes a detached scene snapshot and requires the runner to consume and echo that exact file', () => {
    const binding: SceneRecipeBinding = {
      schemaVersion: 'rag-ime.agent-lab-scene-recipe-binding.v1', sceneId: ENTERPRISE_RAG_SCENE_ID,
      revision: 1, versionId: 'enterprise-rag.validation.luna-prompt-v4-r6.v1', effectScope: 'future_validation_runs',
      recipe: { provider: 'openai-codex', model: 'gpt-5.6-luna', thinkingLevel: 'max', promptProfile: 'coverage-balanced-evidence-gate-v4', promptContractVersion: 'rag-agent-evidence-state-budget-routing-v19', agenticSupplementalLimit: 6, answerOnly: true, developmentOnly: true, split: 'validation', candidateAware: true, unbiasedPromotionClaimAllowed: false },
    };
    const ragExperiment = { ...experiment, experimentId: ENTERPRISE_RAG_RECIPE_EXPERIMENT_ID };
    const result = compileExperimentDispatch(ragExperiment, setup(), '', binding);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.contract.sceneRecipeBinding).toEqual(binding);
    expect(result.contract.sceneRecipeBinding).not.toBe(binding);
    expect(result.contract.sceneRecipeBinding?.recipe).not.toBe(binding.recipe);
    binding.recipe.model = 'changed-after-admission';
    expect(result.contract.sceneRecipeBinding?.recipe.model).toBe('gpt-5.6-luna');
    for (const text of [result.message, result.scenarioPrompt]) {
      expect(text).toContain('--scene-recipe');
      expect(text).toContain('scene-recipe.json');
      expect(text).toContain('conditions.sceneRecipe');
      expect(text).toContain('conditions.parentSceneRecipe');
      expect(text).toContain('--candidate-prompt-file');
      expect(text).toContain('--judge-model');
      const dispatch = JSON.parse(text.split('\n').find((line) => line.startsWith('agentLabDispatch='))!.slice('agentLabDispatch='.length));
      expect(dispatch.sceneRecipeBinding).toEqual(result.contract.sceneRecipeBinding);
    }
    expect(result.scenarioPrompt.length).toBeLessThanOrEqual(8000);
    expect(compileExperimentDispatch(experiment, setup(), '', binding).ok).toBe(false);
    expect(compileExperimentDispatch(ragExperiment, setup(), '', { ...binding, sceneId: 'other-scene' }).ok).toBe(false);
  });

  it('persists the exact bounded task in the ordinary Room scenario prompt and first message', () => {
    const result = compileExperimentDispatch(experiment, setup());
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.contract.baseline.runId).toBe(experiment.baseline.runId);
    expect(result.contract.dataset.manifestSha256).toBe(experiment.dataset.manifestSha256);
    expect(result.contract.budget).toEqual({ maxCandidates: 3, maxEstimatedCostUsd: 2.5, enforcement: 'agent_observed' });
    expect(result.contract.workspace).toEqual({ root: '/tmp/paw-candidates', isolation: 'candidate_copy_required' });
    expect(result.contract.scope.target).toBe('prompt');
    for (const text of [result.message, result.scenarioPrompt]) {
      expect(text).toContain(JSON.stringify(result.contract));
      expect(text).toContain('agent.room.abort');
      expect(text).toContain('agent.room.message');
      expect(text).toContain('Host');
    }
    expect(result.contract.stopConditions).toContainEqual({ kind: 'candidate_limit', value: 3 });
    expect(result.contract.stopConditions).toContainEqual({ kind: 'cost_limit_usd', value: 2.5 });
    expect(result.contract.terminalResults).toContain('no_improvement');
  });

  it('rejects settings whose final Room context would be silently truncated by the host', () => {
    const result = compileExperimentDispatch(experiment, { ...setup(), goal: 'x'.repeat(4000), allowedChanges: 'y'.repeat(2000), stopCondition: 'z'.repeat(2000) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.join(' ')).toContain('过长');
    const extra = compileExperimentDispatch(experiment, setup(), 'context'.repeat(1200));
    expect(extra.ok).toBe(false);
  });

  it.each([
    { maxCandidates: 0 }, { maxCandidates: 1.2 }, { maxCandidates: 101 },
    { budgetUsd: Number.NaN }, { budgetUsd: Number.POSITIVE_INFINITY }, { budgetUsd: 0 },
    { goal: ' ' }, { allowedChanges: '' }, { stopCondition: '' },
    { workspaceRoot: '' }, { workspaceRoot: 'relative/path' }, { workspaceRoot: '/tmp/../' },
  ])('rejects incomplete or unbounded setup: %j', (override) => {
    const result = compileExperimentDispatch(experiment, { ...setup(), ...override });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors.length).toBeGreaterThan(0);
  });

  it('keeps configuration probes separate from implementation repair operators', () => {
    const config = compileExperimentDispatch(experiment, setup());
    const implementation = compileExperimentDispatch(experiment, { ...setup(), layer: 'implementation', target: 'retrieval' });
    expect(config.ok && implementation.ok).toBe(true);
    if (!config.ok || !implementation.ok) return;
    expect(config.contract.repairOperators.every((operator) => operator.layer === 'configuration')).toBe(true);
    expect(config.contract.repairOperators.some((operator) => operator.id === 'prompt_evidence_gate')).toBe(true);
    expect(implementation.contract.repairOperators.every((operator) => operator.layer === 'implementation')).toBe(true);
    expect(implementation.contract.repairOperators.some((operator) => operator.id === 'retrieval_implementation')).toBe(true);
    expect(implementation.contract.counterfactualProbes.every((probe) => probe.status === 'planned')).toBe(true);
    expect(implementation.contract.counterfactualProbes.every((probe) => probe.frozenControls.includes('case_set'))).toBe(true);
    expect(implementation.scenarioPrompt).toContain('隔离');
  });

  it('keeps Held-out and application outside a Validation dispatch and does not mutate the source experiment', () => {
    const original = JSON.stringify(experiment);
    const result = compileExperimentDispatch(experiment, setup());
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.contract.dataset.heldOutAllowed).toBe(false);
    expect(result.contract.application).toBe('separate_action');
    expect(result.contract.budget.enforcement).toBe('agent_observed');
    expect(JSON.stringify(experiment)).toBe(original);
    const heldOut = compileExperimentDispatch({ ...experiment, dataset: { ...experiment.dataset, split: 'held_out' } }, setup());
    expect(heldOut.ok).toBe(false);
  });
});
