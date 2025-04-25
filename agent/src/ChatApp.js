import { useEffect, useState } from "react";
import { io } from "socket.io-client";
import {
  AppBar,
  Toolbar,
  Typography,
  Button,
  TextField,
  Select,
  MenuItem,
  Card,
  Paper,
  Box,
  Tabs,
  Tab,
} from "@mui/material";

const socket = io("http://10.244.3.86:5001");

export default function AgentScreen() {
  // activeChats holds objects: { messages: [...], userName: "..." }
  const [activeChats, setActiveChats] = useState({});
  const [selectedChat, setSelectedChat] = useState(null);
  const [message, setMessage] = useState("");
  const [domain, setDomain] = useState("");
  const [isAgent, setIsAgent] = useState(false);
  const [image, setImage] = useState(null);
  const [notificationCounts, setNotificationCounts] = useState({});

  useEffect(() => {
    Notification.requestPermission();
    const storedAgentId = localStorage.getItem("agentId");
    const storedAgentDomain = localStorage.getItem("agentDomain");
    if (storedAgentId && storedAgentDomain) {
      setIsAgent(true);
      setDomain(storedAgentDomain);
      socket.emit(
        "register_agent",
        {
          domain: storedAgentDomain,
          old_agent_id: storedAgentId,
          agent_id: 1,
          agent_name: localStorage.getItem("agentName") || "Agent",
        },
        (response) => {
          if (response?.agent_connection_id) {
            console.log(
              "Re-registered agent with ID:",
              response.agent_connection_id
            );
            socket.emit("restore_chats", {
              agent_connection_id: response.agent_connection_id,
            });
          } else {
            console.error("Failed to re-register agent");
          }
        }
      );
    }

    socket.on("restore_active_chats", (restoredChats) => {
      console.log("Restored active chats:", restoredChats);
      const transformedChats = {};
      Object.keys(restoredChats).forEach((userId) => {
        transformedChats[userId] = {
          messages: restoredChats[userId].map((msg) => ({
            ...msg,
            from: msg.sender === "agent" ? "You" : "User",
            timestamp: new Date().toLocaleTimeString(),
          })),
          userName: activeChats[userId]?.userName || `User ${userId}`,
        };
      });
      setActiveChats(transformedChats);
      if (!selectedChat && Object.keys(transformedChats).length > 0) {
        setSelectedChat(Object.keys(transformedChats)[0]);
      }
    });

    socket.on("receive_message", (data) => {
      setActiveChats((prev) => {
        if (!prev[data.from]) return prev;
        return {
          ...prev,
          [data.from]: {
            ...prev[data.from],
            messages: [
              ...(prev[data.from]?.messages || []),
              {
                from:
                  data.from === localStorage.getItem("agentId")
                    ? "You"
                    : "User",
                message: data.message,
                image: data.image,
              },
            ],
          },
        };
      });
      if (data.from !== selectedChat) {
        setNotificationCounts((prev) => ({
          ...prev,
          [data.from]: (prev[data.from] || 0) + 1,
        }));
      }
    });

    socket.on("new_live_chat", (data) => {
      // data includes user_connection_id and user_name

      if (Notification.permission === "granted") {
        new Notification("New Live Chat", {
          body: `Chat request from ${data.user_name}`,
          icon: "https://img.freepik.com/free-vector/blue-circle-with-white-user_78370-4707.jpg?semt=ais_hybrid&w=740",
        });
      }
      setActiveChats((prev) => ({
        ...prev,
        [data.user_connection_id]: { messages: [], userName: data.user_name },
      }));
      setSelectedChat((prev) => prev || data.user_connection_id);
    });

    socket.on("user_reconnected", (data) => {
      console.log(`User ${data.user_connection_id} reconnected.`);
      setActiveChats((prev) => {
        if (prev[data.user_connection_id]) return prev;
        return {
          ...prev,
          [data.user_connection_id]: {
            messages: [],
            userName: data.user_name || `User ${data.user_connection_id}`,
          },
        };
      });
    });

    socket.on("chat_ended", (data) => {
      setActiveChats((prev) => {
        const updatedChats = { ...prev };
        delete updatedChats[data.partner_id];
        return updatedChats;
      });
      setSelectedChat((prev) => (prev === data.partner_id ? null : prev));
    });

    socket.on("agent_status", (data) => {
      console.log("Agent status:", data);
    });

    // (Optional) Handle no_agents_available if needed
    socket.on("no_agents_available", (data) => {
      console.warn("No agents available:", data.message);
    });

    return () => {
      socket.off("receive_message");
      socket.off("new_live_chat");
      socket.off("chat_ended");
      socket.off("restore_active_chats");
      socket.off("user_reconnected");
      socket.off("agent_status");
      socket.off("no_agents_available");
    };
  }, [selectedChat, activeChats]);

  const registerAgent = () => {
    if (!domain) return;
    const agent_id = 1;
    const agent_name = "Agent 1"; // Or get this value from an input field
    socket.emit(
      "register_agent",
      { domain, agent_id, agent_name },
      (response) => {
        if (response?.agent_connection_id) {
          localStorage.setItem("agentId", response.agent_connection_id);
          localStorage.setItem("agentDomain", domain);
          localStorage.setItem("agentName", agent_name);
          setIsAgent(true);
          console.log(
            "Registered agent with ID:",
            response.agent_connection_id
          );
        } else {
          console.error("Failed to register agent");
        }
      }
    );
  };

  const sendMessage = () => {
    if (!selectedChat) return;
    const persistentId = localStorage.getItem("agentId");
    if (image) {
      const reader = new FileReader();
      reader.readAsDataURL(image);
      reader.onload = () => {
        socket.emit("send_message", {
          recipient_id: selectedChat,
          image: reader.result,
          persistent_id: persistentId,
        });
        setActiveChats((prev) => ({
          ...prev,
          [selectedChat]: {
            ...prev[selectedChat],
            messages: [
              ...(prev[selectedChat]?.messages || []),
              { from: "You", image: reader.result },
            ],
          },
        }));
        setImage(null);
      };
    } else if (message.trim()) {
      socket.emit("send_message", {
        recipient_id: selectedChat,
        message,
        persistent_id: persistentId,
      });
      setActiveChats((prev) => ({
        ...prev,
        [selectedChat]: {
          ...prev[selectedChat],
          messages: [
            ...(prev[selectedChat]?.messages || []),
            { from: "You", message },
          ],
        },
      }));
      setMessage("");
    }
  };

  const disconnectChat = () => {
    if (!selectedChat) return;
    socket.emit("end_chat", { user_connection_id: selectedChat });
    setActiveChats((prev) => {
      const updatedChats = { ...prev };
      delete updatedChats[selectedChat];
      return updatedChats;
    });
    setSelectedChat(null);
  };

  return (
    <Box sx={{ width: "60%", margin: "auto", mt: 4 }}>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6">Live Chat System - Agent</Typography>
        </Toolbar>
      </AppBar>
      <Card sx={{ mt: 2, p: 2 }}>
        {!isAgent ? (
          <Box>
            <Typography variant="h6">Register as Agent</Typography>
            <Select
              fullWidth
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
            >
              <MenuItem value="">Select Domain</MenuItem>
              <MenuItem value="General">General</MenuItem>
              <MenuItem value="tech_support">Tech Support</MenuItem>
              <MenuItem value="sales">Sales</MenuItem>
              <MenuItem value="billing">Billing</MenuItem>
            </Select>
            <Button
              fullWidth
              variant="contained"
              sx={{ mt: 1 }}
              onClick={registerAgent}
            >
              Register as Agent
            </Button>
          </Box>
        ) : (
          <Typography variant="h6">Registered as Agent in {domain}</Typography>
        )}
      </Card>
      <Paper sx={{ mt: 3, p: 2 }}>
        <Typography variant="h6">Active Chats</Typography>
        <Tabs
          value={selectedChat || false}
          onChange={(e, newValue) => {
            setSelectedChat(newValue);
            setNotificationCounts((prev) => ({ ...prev, [newValue]: 0 }));
          }}
          variant="scrollable"
          scrollButtons="auto"
        >
          {Object.keys(activeChats).map((partnerId, index) => (
            <Tab
              key={partnerId}
              label={
                <Box display="flex" alignItems="center">
                  {activeChats[partnerId].userName || `Chat User ${index + 1}`}
                  {selectedChat !== partnerId &&
                    notificationCounts[partnerId] > 0 && (
                      <Box
                        component="span"
                        sx={{
                          backgroundColor: "red",
                          color: "white",
                          borderRadius: "50%",
                          width: 20,
                          height: 20,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: "0.75rem",
                          fontWeight: "bold",
                          ml: 1,
                        }}
                      >
                        {notificationCounts[partnerId]}
                      </Box>
                    )}
                </Box>
              }
              value={partnerId}
            />
          ))}
        </Tabs>
      </Paper>
      {selectedChat && (
        <Card sx={{ mt: 3, p: 2 }}>
          <Typography variant="h6">
            Chat with {activeChats[selectedChat].userName || selectedChat}
          </Typography>
          <Paper sx={{ maxHeight: 300, overflow: "auto", p: 2, mb: 2 }}>
            {activeChats[selectedChat]?.messages?.map((msg, i) => (
              <Box key={i} sx={{ mb: 2 }}>
                <Typography variant="body2">
                  <strong>{msg.from}:</strong> {msg.message}
                </Typography>
                {msg.image && (
                  <img
                    src={msg.image}
                    alt="Sent"
                    style={{
                      maxWidth: "200px",
                      borderRadius: "10px",
                      marginTop: "5px",
                    }}
                  />
                )}
              </Box>
            ))}
          </Paper>
          <TextField
            fullWidth
            variant="outlined"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Type a message..."
          />
          <Button
            fullWidth
            variant="contained"
            sx={{ mt: 1 }}
            onClick={sendMessage}
          >
            Send
          </Button>
          <Button
            fullWidth
            variant="outlined"
            sx={{ mt: 1 }}
            color="error"
            onClick={disconnectChat}
          >
            End Chat
          </Button>
        </Card>
      )}
    </Box>
  );
}
