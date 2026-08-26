import type { KimiWebApi } from './types';
import { MindmapAgentApi } from './mindmapAgent';

let singleton: KimiWebApi | undefined;

export function getKimiWebApi(): KimiWebApi {
  singleton ??= new MindmapAgentApi();
  return singleton;
}
