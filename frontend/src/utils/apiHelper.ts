export function unwrapApiResponse<T = any>(res: any): {
  code: number;
  msg: string;
  data: T | null;
  raw: any;
} {
  // Support raw Axios responses, ApiService-intercepted responses, and direct backend data.
  // Case 1: raw Axios response.
  if (res && typeof res === 'object' && 'data' in res) {
    const payload = res.data;

    // 1.1 Standard shape: { code, msg, data }.
    if (payload && typeof payload === 'object' && 'code' in payload) {
      return {
        code: Number(payload.code ?? 500),
        msg: payload.msg ?? payload.message ?? 'request failed',
        data: (payload.data ?? null) as T | null,
        raw: payload,
      };
    }

    // 1.2 The interceptor already unwrapped the payload, but it remains under res.data.
    return {
      code: 200,
      msg: 'success',
      data: payload as T,
      raw: payload,
    };
  }

  // Case 2: ApiService has already converted the response to { code, msg, data }.
  if (res && typeof res === 'object' && 'code' in res) {
    return {
      code: Number(res.code ?? 500),
      msg: res.msg ?? res.message ?? 'request failed',
      data: (res.data ?? null) as T | null,
      raw: res,
    };
  }

  // Case 3: the response is the data itself.
  return {
    code: 200,
    msg: 'success',
    data: (res ?? null) as T | null,
    raw: res,
  };
}
