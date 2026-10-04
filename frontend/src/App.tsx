import { ConfigProvider } from 'antd';
import Home from './pages/Home';

function App() {
  return (
    <ConfigProvider
      theme={{
        token: {
          borderRadius: 2,
          fontSize: 16,
        },
        components: {
          Layout: {
            headerBg: '#fff',
            bodyBg: '#fff',
          },
        },
      }}
    >
      <Home />
    </ConfigProvider>
  );
}

export default App;
