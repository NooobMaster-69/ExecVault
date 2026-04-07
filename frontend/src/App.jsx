import { useState, useRef, useCallback, useEffect } from 'react';
import CodeEditor from './components/CodeEditor';
import Controls from './components/Controls';
import OutputPanel from './components/OutputPanel';
import { submitCode, getStatus, getResult } from './api';

const DEFAULT_CODE = {
  python: 'print("Hello, World!")\n',
  node: 'console.log("Hello, World!");\n',
  bash: 'echo "Hello, World!"\n',
  powershell: 'Write-Output "Hello, World!"\n',
};

export default function App() {
  const [language, setLanguage] = useState('python');
  const [code, setCode] = useState(DEFAULT_CODE.python);
  const [timeout, setTimeout_] = useState(10);
  const [userInput, setUserInput] = useState('');
  const [status, setStatus] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [running, setRunning] = useState(false);
  const pollRef = useRef(null);

  const clearPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const handleLanguageChange = (lang) => {
    setLanguage(lang);
    if (DEFAULT_CODE[lang] && code === DEFAULT_CODE[language]) {
      setCode(DEFAULT_CODE[lang]);
    }
  };

  const handleRun = useCallback(async () => {
    if (running) return;
    setRunning(true);
    setStatus('SUBMITTING');
    setResult(null);
    setError(null);
    clearPoll();

    try {
      const data = await submitCode(code, language, timeout, userInput);
      const jobId = data.job_id;
      setStatus('QUEUED');

      pollRef.current = setInterval(async () => {
        try {
          const statusData = await getStatus(jobId);
          setStatus(statusData.status);

          if (['SUCCESS', 'FAILED', 'TIMEOUT'].includes(statusData.status)) {
            clearPoll();
            const resultData = await getResult(jobId);
            setResult(resultData);
            setRunning(false);
          }
        } catch (err) {
          clearPoll();
          setError(err.message);
          setRunning(false);
        }
      }, 1000);
    } catch (err) {
      setError(err.message);
      setStatus(null);
      setRunning(false);
    }
  }, [running, code, language, timeout, userInput, clearPoll]);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        handleRun();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleRun]);

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <div className="logo">
            <div className="logo-icon">
              <svg width="30" height="30" viewBox="0 0 30 30" fill="none">
                <rect x="2" y="2" width="26" height="26" rx="7" stroke="url(#g1)" strokeWidth="2.5" />
                <path d="M10 11l5 4.5-5 4.5" stroke="url(#g1)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                <line x1="17" y1="20" x2="22" y2="20" stroke="url(#g1)" strokeWidth="2.2" strokeLinecap="round" />
                <defs>
                  <linearGradient id="g1" x1="0" y1="0" x2="30" y2="30">
                    <stop offset="0%" stopColor="#c4b5fd" />
                    <stop offset="50%" stopColor="#a78bfa" />
                    <stop offset="100%" stopColor="#7c3aed" />
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <span className="logo-text">ExecVault</span>
          </div>
        </div>
        <div className="header-right">
          <a
            href="https://github.com/NooobMaster-69/ExecVault"
            target="_blank"
            rel="noopener noreferrer"
            className="github-link"
            title="View on GitHub"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
            </svg>
          </a>
        </div>
      </header>

      <main className="main">
        <div className="editor-section">
          <div className="section-header">
            <span className="section-title">Code</span>
            <Controls
              language={language}
              timeout={timeout}
              running={running}
              onLanguageChange={handleLanguageChange}
              onTimeoutChange={setTimeout_}
              onRun={handleRun}
            />
          </div>
          <CodeEditor
            code={code}
            language={language}
            onChange={setCode}
          />
          <div className="section-header" style={{ minHeight: '40px', borderTop: '1px solid var(--border)' }}>
            <span className="section-title">Input (stdin)</span>
          </div>
          <textarea
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder="Provide standard input here..."
            spellCheck="false"
            style={{
              height: '120px',
              width: '100%',
              background: 'transparent',
              color: 'var(--text-primary)',
              border: 'none',
              padding: '16px',
              fontFamily: 'var(--font-mono)',
              fontSize: '13px',
              resize: 'none',
              outline: 'none',
              flexShrink: 0,
            }}
          />
        </div>

        <div className="output-section">
          <div className="section-header">
            <span className="section-title">Output</span>
            {status && (
              <span className={`status-badge status-${status.toLowerCase()}`}>
                {status === 'RUNNING' && <span className="pulse" />}
                {status}
              </span>
            )}
          </div>
          <OutputPanel
            status={status}
            result={result}
            error={error}
            running={running}
          />
        </div>
      </main>
    </div>
  );
}
