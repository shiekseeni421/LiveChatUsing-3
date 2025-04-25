import { useEffect, useState } from "react";
import { io } from "socket.io-client";
import {
  Container,
  TextField,
  Button,
  Box,
  Typography,
  Paper,
  Avatar,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
} from "@mui/material";

const socket = io("http://localhost:5001");

export default function UserScreen() {
  const [messages, setMessages] = useState([]);
  const [message, setMessage] = useState("");
  const [chatPartner, setChatPartner] = useState(null); // { id, name }
  const [userDomain, setUserDomain] = useState("");
  const [isAgentOnline, setIsAgentOnline] = useState(false);
  const [selectedImage, setSelectedImage] = useState(null);
  const [persistentUserId, setPersistentUserId] = useState("");

  useEffect(() => {
    let storedUserId = localStorage.getItem("userId");
    const storedUserDomain = localStorage.getItem("userDomain");

    if (storedUserDomain && storedUserId) {
      setPersistentUserId(storedUserId);
      setUserDomain(storedUserDomain);
      socket.emit(
        "request_live_chat",
        {
          domain: storedUserDomain,
          old_user_id: storedUserId,
          user_id: "user_1",
          user_name: "User 1",
        },
        (response) => {
          if (response?.agent_connection_id) {
            console.log("Chat initiated for user:", storedUserId);
          } else {
            console.error("No agent assigned during reconnection.");
          }
        }
      );
    }

    socket.on("receive_message", (data) => {
      const senderName = data.from === persistentUserId ? "You" : "Agent";
      setMessages((prev) => [
        ...prev,
        {
          from: senderName,
          message: data.message,
          image: data.image || null,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
    });

    socket.on("live_chat_reconnected", (data) => {
      // data includes agent_connection_id and agent_name
      setChatPartner({
        id: data.agent_connection_id,
        name: data.agent_name || "Agent",
      });
      if (data.messages && data.messages.length > 0) {
        const restoredMessages = data.messages.map((msg) => ({
          from: msg.sender === "user" ? "You" : data.agent_name || "Agent",
          message: msg.message,
          image: msg.image || null,
          timestamp: new Date().toLocaleTimeString(),
        }));
        setMessages(restoredMessages);
      }
    });

    socket.on("live_chat_connected", (data) => {
      // data includes agent_connection_id and agent_name
      setChatPartner({
        id: data.agent_connection_id,
        name: data.agent_name || "Agent",
      });
      if (data.messages && data.messages.length > 0) {
        const restoredMessages = data.messages.map((msg) => ({
          from: msg.sender === "user" ? "You" : data.agent_name || "Agent",
          message: msg.message,
          image: msg.image || null,
          timestamp: new Date().toLocaleTimeString(),
        }));
        setMessages(restoredMessages);
      }
    });

    socket.on("new_live_chat", (data) => {
      // Data may include agent_connection_id and agent_name
      setChatPartner({
        id: data.agent_connection_id,
        name: data.agent_name || "Agent",
      });
    });

    socket.on("chat_ended", () => {
      setChatPartner(null);
      setMessages([]);
      localStorage.removeItem("userId");
      localStorage.removeItem("userDomain");
    });

    socket.on("agent_status", (data) => {
      setIsAgentOnline(data.status === "online");
    });

    socket.on("no_agents_available", (data) => {
      alert(data.message || "No agents available. Please try again later.");
    });

    return () => {
      socket.off("receive_message");
      socket.off("live_chat_reconnected");
      socket.off("live_chat_connected");
      socket.off("new_live_chat");
      socket.off("chat_ended");
      socket.off("agent_status");
      socket.off("no_agents_available");
    };
  }, [persistentUserId]);

  const requestChat = () => {
    const user_id = "user_1";
    const user_name = "User 1"; // Or fetch via an input
    if (!userDomain) return alert("Please select a domain to request chat.");
    const uid = localStorage.getItem("userId") || socket.id;
    localStorage.setItem("userId", uid);
    setPersistentUserId(uid);
    localStorage.setItem("userDomain", userDomain);
    socket.emit(
      "request_live_chat",
      { domain: userDomain, old_user_id: uid, user_id, user_name },
      (response) => {
        if (response?.agent_connection_id) {
          console.log("Chat initiated for user:", uid);
        }
      }
    );
  };

  const handleImageUpload = (file) => {
    if (file) {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => {
        setSelectedImage(reader.result);
      };
    }
  };

  const sendMessage = () => {
    if (!chatPartner) {
      console.error("No chat partner assigned yet.");
      return;
    }
    const persistentId = localStorage.getItem("userId");
    if (!message.trim() && !selectedImage) return;
    socket.emit("send_message", {
      recipient_id: chatPartner.id,
      message,
      image: selectedImage,
      persistent_id: persistentId,
    });
    setMessages((prev) => [
      ...prev,
      {
        from: "You",
        message,
        image: selectedImage,
        timestamp: new Date().toLocaleTimeString(),
      },
    ]);
    setMessage("");
    setSelectedImage(null);
  };

  const disconnectChat = () => {
    const user_connection_id = localStorage.getItem("userId");
    socket.emit("end_chat", { user_connection_id });
    localStorage.removeItem("userId");
    localStorage.removeItem("userDomain");
    setChatPartner(null);
    setMessages([]);
  };

  return (
    <Container maxWidth="sm">
      <Paper
        elevation={3}
        sx={{ p: 2, height: "80vh", display: "flex", flexDirection: "column" }}
      >
        <Typography variant="h5" gutterBottom>
          Live Chat
        </Typography>
        <Box my={2}>
          <FormControl fullWidth>
            <InputLabel>Select Domain</InputLabel>
            <Select
              value={userDomain}
              onChange={(e) => setUserDomain(e.target.value)}
            >
              <MenuItem value="tech_support">Tech Support</MenuItem>
              <MenuItem value="sales">Sales</MenuItem>
              <MenuItem value="billing">Billing</MenuItem>
            </Select>
          </FormControl>
          <Button
            variant="contained"
            fullWidth
            sx={{ mt: 1 }}
            onClick={requestChat}
          >
            Request Chat
          </Button>
        </Box>
        <Box sx={{ flexGrow: 1, overflowY: "auto", p: 1 }}>
          {messages.map((msg, i) => (
            <Box
              key={i}
              sx={{
                display: "flex",
                flexDirection: "column",
                alignItems: msg.from === "You" ? "flex-end" : "flex-start",
                mb: 2,
              }}
            >
              {msg.image && (
                <img
                  src={msg.image}
                  alt="Sent"
                  style={{
                    maxWidth: "200px",
                    borderRadius: "10px",
                    marginBottom: "5px",
                  }}
                />
              )}
              <Box
                sx={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent:
                    msg.from === "You" ? "flex-end" : "flex-start",
                }}
              >
                {msg.from !== "You" && (
                  <Avatar sx={{ bgcolor: "primary.main", mr: 1 }}>A</Avatar>
                )}
                <Paper
                  sx={{
                    p: 1.5,
                    bgcolor: msg.from === "You" ? "#DCF8C6" : "#F1F0F0",
                    borderRadius: "10px",
                    maxWidth: "75%",
                  }}
                >
                  {msg.message && (
                    <Typography variant="body1">{msg.message}</Typography>
                  )}
                  <Typography
                    variant="caption"
                    display="block"
                    textAlign="right"
                  >
                    {msg.timestamp}
                  </Typography>
                </Paper>
                {msg.from === "You" && (
                  <Avatar sx={{ bgcolor: "secondary.main", ml: 1 }}>Y</Avatar>
                )}
              </Box>
            </Box>
          ))}
        </Box>
        {selectedImage && (
          <Box sx={{ mt: 1 }}>
            <Typography variant="body2">Image Preview:</Typography>
            <img
              src={selectedImage}
              alt="Preview"
              style={{ maxWidth: "100%", borderRadius: "10px" }}
            />
          </Box>
        )}
        {chatPartner && (
          <Box sx={{ display: "flex", alignItems: "center", mt: 1 }}>
            <TextField
              fullWidth
              variant="outlined"
              placeholder="Type a message..."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <input
              type="file"
              accept="image/*"
              onChange={(e) => handleImageUpload(e.target.files[0])}
              style={{ display: "none" }}
              id="imageUpload"
            />
            <label htmlFor="imageUpload">
              <Button component="span" variant="contained" sx={{ ml: 1 }}>
                📷
              </Button>
            </label>
            <Button onClick={sendMessage} variant="contained" sx={{ ml: 1 }}>
              Send
            </Button>
            <Button
              onClick={disconnectChat}
              color="error"
              variant="outlined"
              sx={{ ml: 1 }}
            >
              Disconnect
            </Button>
          </Box>
        )}
      </Paper>
    </Container>
  );
}
