// 消息类型定义

export interface Reference {
  pdf_sha1: string;
  page_index: number;
  source_file: string;
}

export interface SourceFile {
  file_name: string;
  company_name: string;
}

export interface MessageDetails {
  final_answer?: string;
  step_by_step_analysis?: string;
  reasoning_summary?: string;
  relevant_pages?: number[];
  source_files?: Record<string, SourceFile>;
  references?: Reference[];
}

// 思考步骤
export interface ThinkingStep {
  text: string;
  state: "thinking" | "done";
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: string;
  isStreaming?: boolean;
  details?: MessageDetails;
  thinkingSteps?: ThinkingStep[];
  thinkingCollapsed?: boolean;
}

// SSE 事件类型
export interface SSEEvent {
  type: "status" | "stream_start" | "token" | "done" | "error";
  content: string | object;
}

// 上传响应
export interface UploadResponse {
  status: "success" | "exists" | "error";
  message: string;
  file_name: string;
}

// 知识库文件
export interface KBFile {
  sha1: string;
  file_name: string;
  company_name: string;
}

// 知识库状态
export interface KBStatus {
  total_files: number;
  files: KBFile[];
}
