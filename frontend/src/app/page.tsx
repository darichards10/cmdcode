import { ProblemsTable } from "./components/ProblemsTable";
import { Leaderboard } from "./components/Leaderboard";
import styles from "./page.module.css";

const GITHUB_URL =
  process.env.NEXT_PUBLIC_GITHUB_URL ||
  "https://github.com/darichards10/cmdcode";
const API_URL = process.env.API_URL || "http://localhost:8000";

interface Problem {
  id: number;
  title: string;
  difficulty: string;
  description: string;
}

interface LeaderboardEntry {
  rank: number;
  username: string;
  solved: number;
}

async function getProblems(): Promise<Problem[]> {
  try {
    const res = await fetch(`${API_URL}/api/problems/public`, {
      next: { revalidate: 30 },
    });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

async function getLeaderboard(): Promise<LeaderboardEntry[]> {
  try {
    const res = await fetch(`${API_URL}/api/leaderboard`, {
      next: { revalidate: 30 },
    });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export default async function Home() {
  const [problems, leaderboard] = await Promise.all([
    getProblems(),
    getLeaderboard(),
  ]);

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>
        <span className={styles.accent}>&gt;</span> cmdcode
      </h1>
      <p className={styles.subtitle}>
        Terminal-first competitive programming &mdash;{" "}
        <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
          GitHub
        </a>
      </p>

      <div className={styles.grid}>
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>Problems</h2>
          <ProblemsTable problems={problems} />
        </div>
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>Leaderboard</h2>
          <Leaderboard entries={leaderboard} />
        </div>
      </div>

      <p className={styles.footer}>
        Install the CLI: <code>pip install cmdcode</code> &mdash;{" "}
        <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
          View on GitHub
        </a>
      </p>
    </div>
  );
}
