import React from "react";
import { Composition } from "remotion";
import { END_FRAMES, EndCard } from "./comps/EndCard";
import { HOOK_FRAMES, Hook } from "./comps/Hook";
import { RESULTS_FRAMES, Results } from "./comps/Results";
import { ARCH_FRAMES, Architecture } from "./comps/Architecture";
import { VERIFIER_FRAMES, Verifier } from "./comps/Verifier";
import { TITLE_FRAMES, Title } from "./comps/Title";

const base = { fps: 30, width: 1920, height: 1080 } as const;

export const Root: React.FC = () => (
  <>
    <Composition id="01-title" component={Title} durationInFrames={TITLE_FRAMES} {...base} />
    <Composition id="02-hook" component={Hook} durationInFrames={HOOK_FRAMES} {...base} />
    <Composition id="02-hook-vertical" component={Hook} durationInFrames={HOOK_FRAMES} fps={30} width={1080} height={1920} defaultProps={{ vertical: true }} />
    <Composition id="03-verifier" component={Verifier} durationInFrames={VERIFIER_FRAMES} {...base} />
    <Composition id="04-architecture" component={Architecture} durationInFrames={ARCH_FRAMES} {...base} />
    <Composition id="05-results" component={Results} durationInFrames={RESULTS_FRAMES} {...base} />
    <Composition id="05-results-vertical" component={Results} durationInFrames={RESULTS_FRAMES} fps={30} width={1080} height={1920} defaultProps={{ vertical: true }} />
    <Composition id="06-end-card" component={EndCard} durationInFrames={END_FRAMES} {...base} />
  </>
);
