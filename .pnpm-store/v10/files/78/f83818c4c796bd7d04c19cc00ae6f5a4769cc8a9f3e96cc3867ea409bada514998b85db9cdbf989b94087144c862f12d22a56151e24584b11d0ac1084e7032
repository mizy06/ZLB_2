export type RuleProfileChain = 'core' | 'block' | 'inline' | 'inline2';
export interface RuleProfileRecord {
    chain: RuleProfileChain;
    name: string;
    calls: number;
    hits: number;
    inclusiveMs: number;
    medianMs: number;
    maxMs: number;
    normalCalls: number;
    normalHits: number;
    silentCalls: number;
    silentHits: number;
    samples: number[];
}
export interface RuleProfileSession {
    enabled: boolean;
    fixture?: string;
    mode?: string;
    startedAt: number;
    completedAt?: number;
    records: Record<string, RuleProfileRecord>;
}
export declare function getRuleProfile(env: Record<string, unknown> | undefined | null): RuleProfileSession | null;
export declare function recordRuleInvocation(env: Record<string, unknown> | undefined | null, chain: RuleProfileChain, name: string, durationMs: number, hit: boolean, silent: boolean): void;
export declare function finalizeRuleProfile(env: Record<string, unknown> | undefined | null): RuleProfileSession | null;
