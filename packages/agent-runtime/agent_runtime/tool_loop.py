"""Tool calling loop for agent execution with LLM integration."""

from __future__ import annotations

import logging
import json
from typing import Any, Optional, List
from dataclasses import dataclass, field

from .runtime import (
    AgentRuntime,
    ToolResult,
    ExecutionResult,
    ExecutionMetadata,
    ExecutionState,
)
from llm_provider import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMMessage,
    LLMToolCall,
    LLMToolResult,
    LLMError,
    LLMErrorType,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolLoopConfig:
    """Configuration for tool calling loop."""
    max_iterations: int = 10
    require_tool_confirmation: bool = False
    continue_on_tool_error: bool = True
    stop_on_specific_tool: Optional[str] = None


class ToolCallingLoop:
    """Manages the tool calling loop with LLM integration."""
    
    def __init__(
        self,
        llm_provider: LLMProvider,
        agent_runtime: AgentRuntime,
        config: Optional[ToolLoopConfig] = None,
    ):
        self.llm_provider = llm_provider
        self.agent_runtime = agent_runtime
        self.config = config or ToolLoopConfig()
        self._iteration_count = 0
        self._messages: List[LLMMessage] = []
        self._metadata: Optional[ExecutionMetadata] = None
    
    def reset(self) -> None:
        """Reset the loop state."""
        self._iteration_count = 0
        self._messages.clear()
        self._metadata = None
    
    def execute(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Optional[List[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        metadata: Optional[ExecutionMetadata] = None,
    ) -> ExecutionResult:
        """Execute the tool calling loop."""
        self.reset()
        self._metadata = metadata or self.agent_runtime.create_execution_context("ToolCallingLoop")
        
        # Initialize messages
        self._messages = [
            self.llm_provider.create_system_message(system_prompt),
            self.llm_provider.create_user_message(user_prompt),
        ]
        
        try:
            while self._iteration_count < self.config.max_iterations:
                self._iteration_count += 1
                logger.info(f"Tool calling loop iteration {self._iteration_count}/{self.config.max_iterations}")
                
                # Make LLM request
                response = self._make_llm_request(tools, tool_choice)
                
                # Update metadata
                self._metadata.llm_calls += 1
                if response.usage:
                    self._metadata.total_tokens += response.usage.get("total_tokens", 0)
                
                # Add assistant response to messages
                self._messages.append(
                    self.llm_provider.create_assistant_message(
                        response.content,
                        response.tool_calls,
                    )
                )
                
                # Check if we need to call tools
                if not response.tool_calls:
                    # No tool calls, we're done
                    logger.info("No tool calls in response, completing loop")
                    self._metadata.mark_completed()
                    return ExecutionResult(
                        success=True,
                        content=response.content,
                        metadata=self._metadata,
                    )
                
                # Execute tool calls
                tool_results = self._execute_tool_calls(response.tool_calls)
                
                # Check if we should stop on a specific tool
                if self.config.stop_on_specific_tool:
                    for tool_call in response.tool_calls:
                        tool_name = tool_call.function.get("name") if tool_call.function else ""
                        if tool_name == self.config.stop_on_specific_tool:
                            logger.info(f"Stopping on specific tool: {tool_name}")
                            self._metadata.mark_completed()
                            return ExecutionResult(
                                success=True,
                                content=response.content,
                                metadata=self._metadata,
                            )
                
                # Add tool results to messages
                for tool_result in tool_results:
                    self._messages.append(
                        self.llm_provider.create_tool_message(
                            tool_result.tool_call_id,
                            tool_result.content,
                        )
                    )
                
                # Update metadata
                self._metadata.tool_calls += len(tool_results)
                
                # Check if all tools failed
                if not self.config.continue_on_tool_error:
                    if all(not tr.success for tr in tool_results):
                        error_msg = "All tool executions failed"
                        logger.error(error_msg)
                        self._metadata.mark_failed(error_msg)
                        return ExecutionResult(
                            success=False,
                            content=response.content,
                            metadata=self._metadata,
                        )
            
            # Max iterations reached
            logger.warning(f"Tool calling loop reached max iterations ({self.config.max_iterations})")
            self._metadata.mark_failed("Max iterations reached")
            return ExecutionResult(
                success=False,
                content=self._messages[-1].content if self._messages else "",
                metadata=self._metadata,
            )
            
        except LLMError as e:
            logger.error(f"LLM error in tool calling loop: {str(e)}")
            self._metadata.mark_failed(str(e))
            return ExecutionResult(
                success=False,
                content="",
                metadata=self._metadata,
            )
        except Exception as e:
            logger.error(f"Unexpected error in tool calling loop: {str(e)}")
            self._metadata.mark_failed(str(e))
            return ExecutionResult(
                success=False,
                content="",
                metadata=self._metadata,
            )
    
    def _make_llm_request(
        self,
        tools: Optional[List[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> LLMResponse:
        """Make an LLM request with current messages."""
        request = self.llm_provider.create_request(
            messages=self._messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        return self.llm_provider.chat_completion(request)
    
    def _execute_tool_calls(self, tool_calls: List[LLMToolCall]) -> List[LLMToolResult]:
        """Execute multiple tool calls."""
        results = []
        
        for tool_call in tool_calls:
            try:
                # Parse tool call
                if not tool_call.function:
                    logger.warning(f"Tool call {tool_call.id} has no function")
                    results.append(LLMToolResult(
                        tool_call_id=tool_call.id,
                        content=f"Error: Tool call {tool_call.id} has no function",
                    ))
                    continue
                
                function_name = tool_call.function.get("name")
                function_args = tool_call.function.get("arguments", "{}")
                
                # Parse arguments
                try:
                    arguments = json.loads(function_args)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse tool arguments: {function_args}")
                    results.append(LLMToolResult(
                        tool_call_id=tool_call.id,
                        content=f"Error: Invalid JSON in tool arguments",
                    ))
                    continue
                
                # Execute tool
                tool_result = self.agent_runtime.execute_tool(function_name, arguments)
                
                # Format result
                if tool_result.success:
                    content = tool_result.content
                    if tool_result.data:
                        content = json.dumps(tool_result.data)
                else:
                    content = f"Error: {tool_result.error or 'Tool execution failed'}"
                
                results.append(LLMToolResult(
                    tool_call_id=tool_call.id,
                    content=content,
                ))
                
            except Exception as e:
                logger.error(f"Error executing tool call {tool_call.id}: {str(e)}")
                results.append(LLMToolResult(
                    tool_call_id=tool_call.id,
                    content=f"Error: {str(e)}",
                ))
        
        return results
    
    def get_iteration_count(self) -> int:
        """Get the current iteration count."""
        return self._iteration_count
    
    def get_messages(self) -> List[LLMMessage]:
        """Get the current message history."""
        return self._messages.copy()


__all__ = [
    "ToolLoopConfig",
    "ToolCallingLoop",
]
