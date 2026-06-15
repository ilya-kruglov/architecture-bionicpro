import React, { useState, useEffect } from 'react';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const ReportPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    // Проверка аутентификации при загрузке
    fetch(`${API_URL}/auth/user`, { credentials: 'include' })
      .then(res => {
        if (res.ok) return res.json();
        throw new Error('Not authenticated');
      })
      .then(data => setUser(data))
      .catch(() => setUser(null));
  }, []);

  const login = () => {
    window.location.href = `${API_URL}/auth/login`;
  };

  const logout = async () => {
    await fetch(`${API_URL}/auth/logout`, {
      method: 'POST',
      credentials: 'include'
    });
    window.location.href = '/';
  };

  const downloadReport = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await fetch(`${API_URL}/reports`, {
        credentials: 'include'
      });
      if (!response.ok) throw new Error('Failed to download report');
      // Обработка файла
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  if (user === null) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <button onClick={login} className="px-4 py-2 bg-blue-500 text-white rounded">
          Login
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
      <div className="p-8 bg-white rounded-lg shadow-md">
        <h1 className="text-2xl font-bold mb-6">Usage Reports</h1>
        <p>Welcome, {user.name || user.email}</p>
        <button onClick={downloadReport} disabled={loading} className="mt-4 px-4 py-2 bg-blue-500 text-white rounded">
          {loading ? 'Generating...' : 'Download Report'}
        </button>
        <button onClick={logout} className="mt-4 ml-2 px-4 py-2 bg-gray-500 text-white rounded">
          Logout
        </button>
        {error && <div className="mt-4 text-red-600">{error}</div>}
      </div>
    </div>
  );
};

export default ReportPage;