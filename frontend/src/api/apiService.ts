import axios, {
  AxiosInstance,
  AxiosRequestConfig,
  InternalAxiosRequestConfig,
} from 'axios';

interface ApiServiceOptions {
  baseURL: string;
  timeout?: number;
  headers?: Record<string, string>;
}

class ApiService {
  private instance: AxiosInstance;

  constructor(options: ApiServiceOptions) {
    // All application endpoints share this Axios instance; api.ts selects each domain's base URL.
    this.instance = axios.create({
      baseURL: options.baseURL,
      timeout: options.timeout || 3000000,
      headers: options.headers || { 'Content-Type': 'application/json' },
    });

    this.instance.interceptors.request.use(
      (config: InternalAxiosRequestConfig) => {
        // Keep a shared extension point without modifying request parameters.
        return config;
      },
      (error) => {
        return Promise.reject(error);
      }
    );

  }

  public async get<T = any>(
    url: string,
    config?: AxiosRequestConfig
  ): Promise<T> {
    const response = await this.instance.get<T>(url, config);
    return response.data;
  }

  public async post<T = any>(
    url: string,
    data?: any,
    config?: AxiosRequestConfig
  ): Promise<T> {
    const response = await this.instance.post<T>(url, data, config);
    return response.data;
  }

  public async delete<T = any>(
    url: string,
    config?: AxiosRequestConfig
  ): Promise<T> {
    const response = await this.instance.delete<T>(url, config);
    return response.data;
  }
}

export default ApiService;
