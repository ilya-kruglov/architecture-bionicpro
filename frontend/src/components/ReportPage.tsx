import React, { useState, useEffect } from 'react';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const ReportPage: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState<any>(null);
  const [reportData, setReportData] = useState<any[]>([]);

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
      const response = await fetch(`${API_URL}/reports?period=last_7_days`, {
        credentials: 'include'
      });
      if (!response.ok) throw new Error('Failed to download report');
      const data = await response.json();
      setReportData(data);
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
      <div className="p-8 bg-white rounded-lg shadow-md w-full max-w-4xl">
        <h1 className="text-2xl font-bold mb-6">Usage Reports</h1>
        <p className="mb-4">Welcome, {user.name || user.email}</p>
        <button onClick={downloadReport} disabled={loading} className="px-4 py-2 bg-blue-500 text-white rounded">
          {loading ? 'Generating...' : 'Download Report'}
        </button>
        <button onClick={logout} className="ml-2 px-4 py-2 bg-gray-500 text-white rounded">
          Logout
        </button>
        {error && <div className="mt-4 text-red-600">{error}</div>}

        {reportData.length > 0 && (
          <div className="mt-6 overflow-auto">
            <h2 className="text-xl font-bold mb-2">Report Data</h2>
            <pre className="bg-gray-100 p-4 rounded text-sm">
              {JSON.stringify(reportData, null, 2)}
            </pre>
          </div>
        )}
        {reportData.length === 0 && !loading && !error && (
          <div className="mt-4 text-gray-500">No report data available for this user.</div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;