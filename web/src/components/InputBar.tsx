import { useState, useRef } from "react";
import { uploadFile } from "@/api";
import type { UploadResponse } from "@/types";

interface InputBarProps {
  onSubmit: (question: string) => void;
  isGenerating: boolean;
}

export function InputBar({ onSubmit, isGenerating }: InputBarProps) {
  const [question, setQuestion] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<UploadResponse | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = () => {
    if (!question.trim() || isGenerating) return;
    onSubmit(question);
    setQuestion("");
    // 重置 textarea 高度
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setQuestion(e.target.value);
    // 自适应高度
    const textarea = e.target;
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 144) + "px";
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && file.name.toLowerCase().endsWith(".pdf")) {
      setSelectedFile(file);
      setUploadStatus(null);
    }
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setUploadStatus(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleUpload = async () => {
    if (!selectedFile || isUploading) return;

    setIsUploading(true);
    setUploadStatus(null);

    try {
      const result = await uploadFile(selectedFile);
      setUploadStatus(result);
      if (result.status === "success") {
        // 上传成功后清除文件
        setTimeout(() => {
          setSelectedFile(null);
          setUploadStatus(null);
          if (fileInputRef.current) {
            fileInputRef.current.value = "";
          }
        }, 1500);
      }
    } catch (err) {
      setUploadStatus({
        status: "error",
        message: err instanceof Error ? err.message : "上传失败",
        file_name: "",
      });
    } finally {
      setIsUploading(false);
    }
  };

  const hasContent = question.trim().length > 0;

  return (
    <div className="shrink-0 bg-white px-6 pb-5 pt-2">
      <div className="max-w-[768px] mx-auto">
        {/* 文件预览 */}
        {selectedFile && (
          <div className="mb-2 flex items-center gap-2">
            <div
              className={`inline-flex items-center gap-1.5 bg-[#F1F5F9] rounded-lg px-3 py-1.5 text-[13px] text-[#475569] ${
                uploadStatus?.status === "error" ? "border border-red-300" : ""
              }`}
            >
              {/* 文件图标 */}
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="shrink-0">
                <path d="M4 2h5l4 4v8a1 1 0 01-1 1H4a1 1 0 01-1-1V3a1 1 0 011-1z" stroke="#64748B" strokeWidth="1.5" />
                <path d="M9 2v4h4" stroke="#64748B" strokeWidth="1.5" />
              </svg>
              <span className="max-w-[200px] truncate">{selectedFile.name}</span>
              {/* 上传中旋转图标 */}
              {isUploading && (
                <span className="inline-block w-3 h-3 border-2 border-[#64748B] border-t-transparent rounded-full animate-spin" />
              )}
              {/* 上传成功勾号 */}
              {uploadStatus?.status === "success" && (
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none" className="shrink-0">
                  <path d="M3 8l3.5 3.5L13 5" stroke="#22C55E" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
              {/* 删除按钮 */}
              {!isUploading && uploadStatus?.status !== "success" && (
                <button
                  onClick={handleRemoveFile}
                  className="ml-0.5 text-[#94A3B8] hover:text-[#475569] transition-colors"
                >
                  <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                    <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                </button>
              )}
            </div>
            {/* 上传按钮 */}
            {!isUploading && !uploadStatus && (
              <button
                onClick={handleUpload}
                className="text-[12px] text-[#2563EB] hover:underline"
              >
                添加到数据库
              </button>
            )}
            {/* 上传状态提示 */}
            {uploadStatus && uploadStatus.status !== "success" && (
              <span
                className={`text-[12px] ${
                  uploadStatus.status === "error"
                    ? "text-red-500"
                    : "text-amber-600"
                }`}
              >
                {uploadStatus.message}
              </span>
            )}
          </div>
        )}

        {/* 输入框容器 */}
        <div className="flex items-end gap-2 bg-white border border-[#E2E8F0] rounded-2xl px-3 py-2 shadow-[0_2px_8px_rgba(0,0,0,0.06)] focus-within:border-[#2563EB] focus-within:shadow-[0_2px_12px_rgba(37,99,235,0.12)] transition-all">
          {/* 附件按钮 */}
          <button
            onClick={() => fileInputRef.current?.click()}
            className="shrink-0 p-1 text-[#94A3B8] hover:text-[#2563EB] transition-colors self-end mb-0.5"
            title="上传 PDF 文件"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
            </svg>
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            onChange={handleFileSelect}
            className="hidden"
          />

          {/* 文本输入框 */}
          <textarea
            ref={textareaRef}
            value={question}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="输入您的问题..."
            disabled={isGenerating}
            rows={1}
            className="flex-1 resize-none border-0 bg-transparent text-[14px] leading-[1.5] text-[#1E293B] placeholder:text-[#94A3B8] focus:outline-none disabled:opacity-50 py-1"
            style={{ maxHeight: "144px" }}
          />

          {/* 发送按钮 */}
          <button
            onClick={handleSubmit}
            disabled={!hasContent || isGenerating}
            className={`shrink-0 w-8 h-8 flex items-center justify-center rounded-full transition-colors self-end mb-0.5 ${
              hasContent && !isGenerating
                ? "bg-[#2563EB] text-white hover:bg-[#1d4ed8]"
                : "bg-[#E2E8F0] text-[#94A3B8]"
            }`}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>

        {/* 底部提示 */}
        <p className="text-center text-[11px] text-[#CBD5E1] mt-2">
          基于 RAG 知识库回答，每次提问独立，不保留上下文
        </p>
      </div>
    </div>
  );
}
