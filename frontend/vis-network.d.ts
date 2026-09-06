// Type shim for vis-network — full types are bundled with the package but
// this module declaration ensures the dynamic import resolves cleanly under
// Next.js / Turbopack when @types/vis-network is absent.
declare module "vis-network/standalone" {
  export * from "vis-network"
  export { Network, DataSet, DataView } from "vis-network"
}
