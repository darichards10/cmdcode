import styles from "./Leaderboard.module.css";

interface LeaderboardEntry {
  rank: number;
  username: string;
  solved: number;
}

export function Leaderboard({ entries }: { entries: LeaderboardEntry[] }) {
  if (entries.length === 0) {
    return <p className={styles.empty}>No solves yet. Be the first!</p>;
  }

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>Rank</th>
          <th>User</th>
          <th>Solved</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => {
          const rankClass =
            entry.rank <= 3 ? styles[`rank${entry.rank}`] : "";
          return (
            <tr key={entry.username}>
              <td>
                <span className={`${styles.rank} ${rankClass}`}>
                  #{entry.rank}
                </span>
              </td>
              <td>{entry.username}</td>
              <td className={styles.solved}>{entry.solved}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
