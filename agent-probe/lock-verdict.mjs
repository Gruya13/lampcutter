export function lockVerdict({ lock, sha256, git, requireGit }) {
  if (lock === undefined) return "unlocked";
  if (lock.casesSha256 !== sha256) return "changed";
  if (git.blobMatchesLock === false) return "unproven";
  if (requireGit === true && git.state !== "clean") return "uncommitted";
  if (requireGit === true && (typeof lock.gitRevision !== "string" || lock.gitRevision === "")) return "unproven";
  return "ok";
}
