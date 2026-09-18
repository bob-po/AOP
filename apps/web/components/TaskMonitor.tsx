'use client';

import React, { useState, useEffect } from 'react';
import { useTaskWebSocket } from '../hooks/useWebSocket';

interface TaskMonitorProps {
  taskId: string;
}

export default function TaskMonitor({ taskId }: TaskMonitorProps) {
  const {
    isConnected,
    connectionError,
    taskState,
    taskEvents,
    disconnect,
    reconnect,
  } = useTaskWebSocket(taskId);

  const [autoReconnect, setAutoReconnect] = useState(true);

  const latestEvent = taskEvents.length > 0 ? taskEvents[taskEvents.length - 1] : null;

  const getEventColor = (eventType: string) => {
    switch (eventType) {
      case 'task_created':
        return 'bg-blue-100 text-blue-800';
      case 'task_completed':
        return 'bg-green-100 text-green-800';
      case 'task_waiting_for_user':
        return 'bg-yellow-100 text-yellow-800';
      case 'workflow_started':
        return 'bg-purple-100 text-purple-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  return (
    <div className="space-y-4">
      {/* Connection Status */}
      <div className="flex items-center justify-between p-4 bg-white rounded-lg shadow">
        <div className="flex items-center space-x-2">
          <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm font-medium">
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
          {connectionError && (
            <span className="text-sm text-red-600">{connectionError}</span>
          )}
        </div>
        <div className="flex items-center space-x-2">
          <label className="flex items-center space-x-1 text-sm">
            <input
              type="checkbox"
              checked={autoReconnect}
              onChange={(e) => setAutoReconnect(e.target.checked)}
              className="rounded"
            />
            <span>Auto Reconnect</span>
          </label>
          <button
            onClick={isConnected ? disconnect : reconnect}
            className="px-3 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
          >
            {isConnected ? 'Disconnect' : 'Connect'}
          </button>
        </div>
      </div>

      {/* Task State */}
      {taskState && (
        <div className="p-4 bg-white rounded-lg shadow">
          <h3 className="text-lg font-semibold mb-3">Task State</h3>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="font-medium">Status:</span>
              <span className={`ml-2 px-2 py-1 rounded ${getEventColor(taskState.status)}`}>
                {taskState.status}
              </span>
            </div>
            <div>
              <span className="font-medium">Created:</span>
              <span className="ml-2">{new Date(taskState.created_at).toLocaleString()}</span>
            </div>
            {taskState.title && (
              <div className="col-span-2">
                <span className="font-medium">Title:</span>
                <span className="ml-2">{taskState.title}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Latest Event */}
      {latestEvent && (
        <div className="p-4 bg-white rounded-lg shadow">
          <h3 className="text-lg font-semibold mb-3">Latest Event</h3>
          <div className={`p-3 rounded ${getEventColor(latestEvent.event_type || '')}`}>
            <div className="font-medium">{latestEvent.event_type}</div>
            <div className="text-sm mt-1">
              {JSON.stringify(latestEvent.data, null, 2)}
            </div>
          </div>
        </div>
      )}

      {/* Event Log */}
      <div className="p-4 bg-white rounded-lg shadow">
        <h3 className="text-lg font-semibold mb-3">Event Log ({taskEvents.length})</h3>
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {taskEvents.length === 0 ? (
            <p className="text-gray-500 text-sm">No events yet</p>
          ) : (
            taskEvents.map((event, index) => (
              <div
                key={index}
                className={`p-2 rounded text-sm ${getEventColor(event.event_type || '')}`}
              >
                <div className="font-medium">{event.event_type}</div>
                <div className="text-xs text-gray-600">
                  {new Date(event.timestamp || Date.now()).toLocaleTimeString()}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}