import styles from "./ProblemsTable.module.css";

interface Problem {
  id: number;
  title: string;
  difficulty: string;
}

export function ProblemsTable({ problems }: { problems: Problem[] }) {
  if (problems.length === 0) {
    return <p className={styles.empty}>No problems yet.</p>;
  }

  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th>#</th>
          <th>Title</th>
          <th>Difficulty</th>
        </tr>
      </thead>
      <tbody>
        {problems.map((p) => (
          <tr key={p.id}>
            <td>{p.id}</td>
            <td>{p.title}</td>
            <td>
              <span
                className={`${styles.badge} ${styles[`badge${p.difficulty}`] || ""}`}
              >
                {p.difficulty}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
