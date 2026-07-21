import * as React from "react";
import { Canvas } from "@react-three/fiber";
import { Bounds, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

export interface StlBodySpec {
  /** Blob object URL for this body. */
  url: string;
  /** Material color for this body (e.g. neutral gray outline, accent text). */
  color: string;
}

interface StlPreviewProps {
  /** One entry per printable body -- one for bins, two (outline + text) for labels. */
  bodies: StlBodySpec[];
  className?: string;
}

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; geometry: THREE.BufferGeometry }
  | { status: "error"; message: string };

/**
 * Loads a single STL body via `STLLoader` given a blob object URL. Manual
 * load/error state (rather than `@react-three/fiber`'s Suspense-based
 * `useLoader`) so a body that fails to parse degrades to an inline error
 * instead of requiring a class-component error boundary around the canvas.
 */
function useStlGeometry(url: string | null): LoadState {
  const [state, setState] = React.useState<LoadState>({ status: "idle" });

  React.useEffect(() => {
    if (!url) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    let loaded: THREE.BufferGeometry | null = null;
    setState({ status: "loading" });

    const loader = new STLLoader();
    loader.load(
      url,
      (geometry) => {
        if (cancelled) {
          geometry.dispose();
          return;
        }
        loaded = geometry;
        setState({ status: "loaded", geometry });
      },
      undefined,
      () => {
        if (cancelled) return;
        setState({ status: "error", message: "Failed to load STL file." });
      },
    );

    return () => {
      cancelled = true;
      loaded?.dispose();
    };
  }, [url]);

  return state;
}

function StlBody({ geometry, color }: { geometry: THREE.BufferGeometry; color: string }) {
  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial color={color} roughness={0.55} metalness={0.05} />
    </mesh>
  );
}

/**
 * Loads one body's geometry and renders it once loaded (nothing while
 * pending/errored), reporting its load status up to the parent via
 * `onStatusChange` so `StlPreview` can drive one shared loading/error
 * overlay without calling `useStlGeometry` itself over a variable-length
 * array (which would violate the Rules of Hooks).
 */
function StlBodyLoader({
  url,
  color,
  onStatusChange,
}: StlBodySpec & { onStatusChange: (status: LoadState["status"]) => void }) {
  const state = useStlGeometry(url);

  React.useEffect(() => {
    onStatusChange(state.status);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.status]);

  if (state.status !== "loaded") return null;
  return <StlBody geometry={state.geometry} color={color} />;
}

/**
 * Renders an arbitrary set of STL bodies produced by a generator (one body
 * for a Gridfinity bin, two -- outline + text -- for a label's filament-swap
 * pair) inside a `@react-three/fiber` canvas, each in its own material color.
 *
 * Bodies keep the local coordinates they were exported with -- deliberately
 * NOT calling `geometry.center()` on each independently, since for the
 * two-body label case that would shift them off their shared origin and
 * destroy the alignment the two filament-swap bodies rely on to overlay
 * correctly when printed. Instead `<Bounds fit clip observe>` computes the
 * camera framing from their *combined* bounding box, which doesn't touch
 * geometry data at all.
 */
export function StlPreview({ bodies, className }: StlPreviewProps) {
  // Per-body load status, keyed by index, reported up by each
  // <StlBodyLoader>. Driving the shared loading/error overlay this way
  // (rather than calling `useStlGeometry` here over `bodies.map(...)`) keeps
  // this component's own hook calls unconditional regardless of how many
  // bodies are passed in.
  const [statuses, setStatuses] = React.useState<Record<number, LoadState["status"]>>({});

  const anyError = bodies.some((_, i) => statuses[i] === "error");
  const allLoaded = bodies.length > 0 && bodies.every((_, i) => statuses[i] === "loaded");
  const stillLoading = !anyError && !allLoaded;

  return (
    <div className={className ?? "relative h-full w-full"}>
      <Canvas
        camera={{ fov: 45, near: 0.1, far: 2000, position: [60, 60, 60] }}
        onCreated={({ gl }) => gl.setClearColor("#000000", 0)}
      >
        <ambientLight intensity={0.65} />
        <directionalLight position={[40, 60, 30]} intensity={1.1} />
        <directionalLight position={[-30, -20, -40]} intensity={0.35} />
        <Bounds fit clip observe margin={1.4}>
          <group>
            {bodies.map((body, i) => (
              <StlBodyLoader
                key={`${body.url}-${i}`}
                url={body.url}
                color={body.color}
                onStatusChange={(status) =>
                  setStatuses((prev) => (prev[i] === status ? prev : { ...prev, [i]: status }))
                }
              />
            ))}
          </group>
        </Bounds>
        <OrbitControls makeDefault enableDamping dampingFactor={0.15} />
      </Canvas>
      {stillLoading && !anyError && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background/60 text-sm text-muted-foreground">
          Loading preview…
        </div>
      )}
      {anyError && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background/80 text-sm text-destructive">
          Failed to load 3D preview.
        </div>
      )}
    </div>
  );
}
