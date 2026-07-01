window.GAME_DATA = {
  "task": "sliding-puzzle",
  "models": [
    {
      "key": "gemini-3-pro",
      "label": "Gemini 3 Pro",
      "umm": false
    },
    {
      "key": "gpt-5.1",
      "label": "GPT-5.1",
      "umm": false
    },
    {
      "key": "emu-3.5",
      "label": "EMU 3.5",
      "umm": true
    }
  ],
  "puzzles": [
    {
      "id": "level01_puzzle_0003",
      "level": 1,
      "num_moves": 1,
      "grid_size": 2,
      "initial_state": [
        [
          1,
          2
        ],
        [
          3,
          -1
        ]
      ],
      "target_state": [
        [
          1,
          2
        ],
        [
          -1,
          3
        ]
      ],
      "solution_moves": [
        "left"
      ],
      "target_image": "static/game/puzzles/level01_puzzle_0003/target.png",
      "models": {
        "gemini-3-pro": {
          "answer": "The puzzle is already solved",
          "correct": false,
          "reasoning": "Based on the visual analysis of the puzzle state:\n\n1.  **Identify Tiles:**\n    *   **Top-Left (Tile A):** Contains the knife handle (left side), dark cloth, and the main bulb of the vegetable. The knife blade starts here.\n    *   **Top-Right (Tile B):** Contains the rest of the vegetable (stalks), background, and the knife blade continuing from the handle section.\n    *   **Bottom-Left (Tile C):** Contains the wooden cutting board and the sharp edge of the knife blade. There is a \"heel\" highlight on the left that aligns vertically with the handle in the Top-Left tile. The shadow on the board also aligns with the dark objects above.\n    *   **Bottom-Right (Tile D):** This is the **Blank** (black) tile.\n\n2.  **Analyze Alignment:**\n    *   **Horizontal Seam (Top):** The knife blade and the green vegetable stalk flow continuously from the Top-Left tile to the Top-Right tile. The reflection on the blade is consistent. These two are correctly placed relative to each other.\n    *   **Vertical Seam (Left):** The Top-Left tile shows the knife body and handle. The Bottom-Left tile shows the wooden board underneath. The shadow of the handle falls naturally onto the board in the Bottom-Left tile. The \"heel\" of the knife blade (start of the sharp edge) begins on the left of the Bottom-Left tile, corresponding to the handle position above.\n    *   **Conclusion:** The three visible image tiles are currently in their correct positions relative to the original image (Top-Left, Top-Right, Bottom-Left). The blank tile is in the Bottom-Right position.\n\n3.  **Determination:**\n    The puzzle is already in the **solved state**. The image is coherent, and the tiles are in their correct original positions (1, 2, 3, Blank). Therefore, **no moves are required**.\n\n```json\n{\"answer\": \"The puzzle is already solved\"}\n```",
          "generated_images": []
        },
        "gpt-5.1": {
          "answer": "",
          "correct": false,
          "reasoning": "{\"answer\": \"\"}",
          "generated_images": []
        },
        "emu-3.5": {
          "answer": "down left up right",
          "correct": false,
          "reasoning": "To solve the puzzle, I need to determine the sequence of moves required to align the tiles correctly. First, I observe that the blank tile is currently positioned near the top right corner. To start, I'll move the blank tile downward to create more space and facilitate further movements. After moving the blank tile down, I notice that the next tile to be aligned is located below it. Therefore, I will move the blank tile left to swap positions with the tile below. Following this, I observe that the tile to the left of the blank is misaligned; hence, I'll move the blank tile up to align it properly. Finally, I need to adjust the tile on the far right by moving the blank tile to the right. Summarizing these steps, the sequence of moves required is: down, left, up, right. Therefore, the answer is: {\"answer\": \"down left up right\"}.To finish the task, I need to do the following steps: Step 1: Move the blank tile down. Step 2: Move the blank tile left. Step 3: Move the blank tile up. Step 4: Move the blank tile right. I have already done 1 steps, and there are 3 steps left. Current Step: Move the blank tile left. Current Step: Move the blank tile up. Current Step: Move the blank tile right.",
          "generated_images": [
            "generated_images/3/generated_image_0.png",
            "generated_images/3/generated_image_1.png",
            "generated_images/3/generated_image_2.png"
          ]
        }
      }
    },
    {
      "id": "level02_puzzle_0001",
      "level": 2,
      "num_moves": 2,
      "grid_size": 2,
      "initial_state": [
        [
          1,
          -1
        ],
        [
          3,
          2
        ]
      ],
      "target_state": [
        [
          1,
          2
        ],
        [
          -1,
          3
        ]
      ],
      "solution_moves": [
        "down",
        "left"
      ],
      "target_image": "static/game/puzzles/level02_puzzle_0001/target.png",
      "models": {
        "gemini-3-pro": {
          "answer": "down left",
          "correct": true,
          "reasoning": "Based on the visual evidence in the tiles:\n\n1.  **Analyze the Tiles:**\n    *   **Tile (0,0):** Shows the top-left part of a miniature guillotine model (top frame, blade mechanism). This is the correct starting position (Top-Left).\n    *   **Tile (0,1):** This is the **Blank** tile.\n    *   **Tile (1,0):** Shows a hand pulling a string. The string angle suggests it is being pulled from above and to the left.\n    *   **Tile (1,1):** Shows a vertical post on the left edge and a taut string going from top-left to bottom-right.\n\n2.  **Determine the Correct Layout:**\n    *   **Top Row:** The post on the right edge of Tile (0,0) aligns with the post on the left edge of Tile (1,1). This implies Tile (1,1) should be to the right of Tile (0,0). So, the **Post & String** tile belongs at **(0,1)**.\n    *   **Bottom Row:** The string in the **Post & String** tile goes down towards the right. The string in the **Hand** tile comes from the top-left. This creates a continuous line if the **Hand** tile is placed below the **Post & String** tile. So, the **Hand** tile belongs at **(1,1)**.\n    *   **Missing Piece:** The bottom-left corner (base of the guillotine) appears to be the missing part, meaning the **Blank** tile should end up at **(1,0)**.\n\n3.  **Target Configuration:**\n    *   (0,0): Guillotine Top\n    *   (0,1): Post & String\n    *   (1,0): Blank\n    *   (1,1): Hand\n\n4.  **Solve the Puzzle:**\n    *   **Current State:**\n        [(0,0) Top] [(0,1) Blank]\n        [(1,0) Hand] [(1,1) Post]\n    *   **Move 1:** Move the **Blank** tile **down**.\n        *   This swaps the Blank with the Post tile.\n        *   State becomes:\n            [(0,0) Top] [(0,1) Post]\n            [(1,0) Hand] [(1,1) Blank]\n        *   Now the Top and Post tiles are correctly placed.\n    *   **Move 2:** Move the **Blank** tile **left**.\n        *   This swaps the Blank with the Hand tile.\n        *   State becomes:\n            [(0,0) Top] [(0,1) Post]\n            [(1,0) Blank] [(1,1) Hand]\n        *   All tiles are now in their correct positions relative to each other.\n\nThe shortest sequence of moves is **down** then **left**.\n\n```json\n{\"answer\": \"down left\"}\n```",
          "generated_images": []
        },
        "gpt-5.1": {
          "answer": "down",
          "correct": false,
          "reasoning": "{\"answer\": \"down\"}",
          "generated_images": []
        },
        "emu-3.5": {
          "answer": "up right down left up",
          "correct": false,
          "reasoning": "To solve the puzzle, we need to follow the rules and swap the blank tile with the adjacent image tile in valid directions. Here is the sequence of moves and the corresponding puzzle states:\n\n1. Up\n2. Right\n3. Down\n4. Left\n5. Up\n\nAfter following these moves, the puzzle will be solved and the original image will be restored. The final answer is: {\"answer\": \"up right down left up\"}.<|extra_61|>To finish the task, I need to do the following steps: Step 1: Move the blank tile up. Step 2: Move the blank tile right. Step 3: Move the blank tile down. Step 4: Move the blank tile left. Step 5: Move the blank tile up. I have already done 0 steps, and there are 5 steps left. Current Step: Move the blank tile up. Current Step: Move the blank tile right. Current Step: Move the blank tile down. Current Step: Move the blank tile left. Current Step: Move the blank tile up.",
          "generated_images": [
            "generated_images/1/generated_image_0.png",
            "generated_images/1/generated_image_1.png",
            "generated_images/1/generated_image_2.png",
            "generated_images/1/generated_image_3.png",
            "generated_images/1/generated_image_4.png"
          ]
        }
      }
    },
    {
      "id": "level03_puzzle_0003",
      "level": 3,
      "num_moves": 3,
      "grid_size": 2,
      "initial_state": [
        [
          2,
          -1
        ],
        [
          1,
          3
        ]
      ],
      "target_state": [
        [
          1,
          2
        ],
        [
          3,
          -1
        ]
      ],
      "solution_moves": [
        "left",
        "down",
        "right"
      ],
      "target_image": "static/game/puzzles/level03_puzzle_0003/target.png",
      "models": {
        "gemini-3-pro": {
          "answer": "left down",
          "correct": false,
          "reasoning": "To solve the sliding tile puzzle, we first need to identify the correct position for each image tile to reconstruct the original coherent scene.\n\n**1. Analyze the Tiles:**\n*   **Tile A (Top-Left in input, position 0,0):** Shows the top part of a large rectangular cleaver blade, some green onion stems on the left, and a background with sky/trees. Since it contains the sky and the top edge of the main object (cleaver), this tile belongs in the top row. Let's tentatively place it at **(0,1)** (Top-Right) because the cleaver handle is typically to the left, but here we see stems on the left and blade on the right. However, looking at the other tiles, Tile C contains the bottom of the blade.\n*   **Tile B (Bottom-Left in input, position 1,0):** Shows a pile of whole white onions and a dark cloth.\n*   **Tile C (Bottom-Right in input, position 1,1):** Shows the bottom-right corner of the cleaver blade (sharp tip) resting on a wooden cutting board. This definitively belongs at **(1,1)** (Bottom-Right).\n*   **Blank Tile (Top-Right in input, position 0,1):** The empty space.\n\n**2. Determine Relative Positions:**\n*   **Vertical Connection (A and C):** Tile A shows the top face of the cleaver. Tile C shows the bottom edge of the cleaver. For the metal blade to look continuous, Tile A must be directly above Tile C. Since C is fixed at (1,1) (bottom-right corner of the blade), Tile A must be at **(0,1)** (top-right).\n*   **Horizontal Connection (B and A):** With A at (0,1), we need a tile at (0,0). Tile B contains onions. In Tile A, we see green stems on the left edge. Logically, stems grow from onion bulbs. If Tile B is to the left of Tile A, the pile of onions in B would connect to the stems in A. This creates a coherent \"onions on the left, cleaver on the right\" composition. So Tile B belongs at **(0,0)**.\n*   **Blank Position:** This leaves the position **(1,0)** (Bottom-Left) for the blank tile. This makes sense as the area to the left of the cleaver tip (which is in C) would be the wooden table, which is the missing piece.\n\n**3. Target Configuration:**\n*   **Row 0:** Tile B | Tile A\n*   **Row 1:** Blank | Tile C\n\n**4. Move Sequence:**\n*   **Current State:**\n    Row 0: Tile A, Blank\n    Row 1: Tile B, Tile C\n*   **Goal:** Move Tile B to (0,0) and Tile A to (0,1).\n    1.  **Move Blank Left:** The blank moves from (0,1) to (0,0), swapping with Tile A.\n        *   *New State:* Blank, Tile A / Tile B, Tile C\n    2.  **Move Blank Down:** The blank moves from (0,0) to (1,0), swapping with Tile B.\n        *   *New State:* Tile B, Tile A / Blank, Tile C\n\nThis matches our target configuration exactly.\n\n```json\n{\"answer\": \"left down\"}\n```",
          "generated_images": []
        },
        "gpt-5.1": {
          "answer": "down",
          "correct": false,
          "reasoning": "{\"answer\": \"down\"}",
          "generated_images": []
        },
        "emu-3.5": {
          "answer": "up right down left up",
          "correct": false,
          "reasoning": "{\"answer\": \"up right down left up\"}",
          "generated_images": []
        }
      }
    },
    {
      "id": "level04_puzzle_0009",
      "level": 4,
      "num_moves": 4,
      "grid_size": 2,
      "initial_state": [
        [
          2,
          3
        ],
        [
          -1,
          1
        ]
      ],
      "target_state": [
        [
          1,
          2
        ],
        [
          -1,
          3
        ]
      ],
      "solution_moves": [
        "right",
        "up",
        "left",
        "down"
      ],
      "target_image": "static/game/puzzles/level04_puzzle_0009/target.png",
      "models": {
        "gemini-3-pro": {
          "answer": "right up left down",
          "correct": true,
          "reasoning": "Based on the visual analysis of the puzzle tiles:\n\n1.  **Identify the Tiles:**\n    *   **Tile A (currently at 0,0 - Top Left):** Shows a dog's ear with the inner part facing left (viewer's right). There is dark grey fabric on the right edge. This is the **Top-Right** tile.\n    *   **Tile B (currently at 0,1 - Top Right):** Shows a dog's nose and mouth on the left side, with white chest fur and dark fabric on the bottom right. Since the nose is central to the face, and on the left of this tile, this tile belongs on the right side of the bottom row to center the snout. This is the **Bottom-Right** tile.\n    *   **Tile C (currently at 1,0 - Bottom Left):** This is the **Blank** tile.\n    *   **Tile D (currently at 1,1 - Bottom Right):** Shows a dog's ear with the inner part facing right (viewer's left) and a fence background on the left. This is the **Top-Left** tile.\n\n2.  **Determine the Target Configuration:**\n    *   **Top-Left:** Tile D (Fence, Right Ear)\n    *   **Top-Right:** Tile A (Left Ear, Fabric)\n    *   **Bottom-Left:** Blank (Missing left shoulder/snout)\n    *   **Bottom-Right:** Tile B (Nose, Chest)\n\n    The goal layout is:\n    [ D, A ]\n    [ _, B ]\n\n3.  **Determine the Moves:**\n    *   **Current Layout:**\n        [ A, B ]\n        [ _, D ]\n        (Where A=Tile 1, B=Tile 2, D=Tile 3, _=Blank)\n    *   We need to rotate the positions of A, B, and D. Specifically, D needs to go to (0,0), A to (0,1), and B to (1,1). This is a clockwise rotation of the tiles.\n    *   To rotate tiles clockwise, we move the blank counter-clockwise around the grid.\n\n    **Sequence:**\n    1.  **Right:** Move blank from (1,0) to (1,1). Swaps with D.\n        Grid becomes:\n        [ A, B ]\n        [ D, _ ]\n    2.  **Up:** Move blank from (1,1) to (0,1). Swaps with B.\n        Grid becomes:\n        [ A, _ ]\n        [ D, B ]\n    3.  **Left:** Move blank from (0,1) to (0,0). Swaps with A.\n        Grid becomes:\n        [ _, A ]\n        [ D, B ]\n    4.  **Down:** Move blank from (0,0) to (1,0). Swaps with D.\n        Grid becomes:\n        [ D, A ]\n        [ _, B ]\n\n    This matches the target configuration perfectly.\n\n```json\n{\"answer\": \"right up left down\"}\n```",
          "generated_images": []
        },
        "gpt-5.1": {
          "answer": "right",
          "correct": false,
          "reasoning": "{\"answer\": \"right\"}",
          "generated_images": []
        },
        "emu-3.5": {
          "answer": "up right down left up",
          "correct": false,
          "reasoning": "{\"answer\": \"up right down left up\"}",
          "generated_images": []
        }
      }
    },
    {
      "id": "level05_puzzle_0011",
      "level": 5,
      "num_moves": 5,
      "grid_size": 2,
      "initial_state": [
        [
          2,
          3
        ],
        [
          -1,
          1
        ]
      ],
      "target_state": [
        [
          1,
          2
        ],
        [
          3,
          -1
        ]
      ],
      "solution_moves": [
        "right",
        "up",
        "left",
        "down",
        "right"
      ],
      "target_image": "static/game/puzzles/level05_puzzle_0011/target.png",
      "models": {
        "gemini-3-pro": {
          "answer": "right up left down right",
          "correct": true,
          "reasoning": "Based on the visual analysis of the puzzle tiles:\n\n1.  **Analyze the Tiles:**\n    *   **Tile A (Top-Left in scrambled grid):** Shows the rear body/back of a grey Schnauzer and a brick wall background.\n    *   **Tile B (Top-Right in scrambled grid):** Shows the dog's chest (white fur), a collar tag, and grass on the left side.\n    *   **Tile D (Bottom-Right in scrambled grid):** Shows the dog's head (facing left), eye, and ear.\n    *   **Blank Tile (Bottom-Left in scrambled grid):** This is the empty space.\n\n2.  **Determine the Goal Configuration:**\n    *   **Anatomy:** The Head (Tile D) must be above the Chest (Tile B). The Back (Tile A) must be adjacent to the Head. Since the dog is facing left (snout points left), the Back (Tile A) must be to the right of the Head (Tile D).\n    *   **Target Layout:**\n        *   Top-Left (0,0): **Tile D** (Head)\n        *   Top-Right (0,1): **Tile A** (Back)\n        *   Bottom-Left (1,0): **Tile B** (Chest)\n        *   Bottom-Right (1,1): **Blank**\n    *   This arrangement puts the head above the chest and the back trailing to the right, creating a coherent image.\n\n3.  **Calculate the Moves:**\n    *   **Start State:**\n        A  B\n        _  D\n    *   **Move 1: Right** (Move blank right)\n        *   Swaps Blank and D.\n        *   State:\n            A  B\n            D  _\n    *   **Move 2: Up** (Move blank up)\n        *   Swaps Blank and B.\n        *   State:\n            A  _\n            D  B\n    *   **Move 3: Left** (Move blank left)\n        *   Swaps Blank and A.\n        *   State:\n            _  A\n            D  B\n    *   **Move 4: Down** (Move blank down)\n        *   Swaps Blank and D.\n        *   State:\n            D  A\n            _  B\n    *   **Move 5: Right** (Move blank right)\n        *   Swaps Blank and B.\n        *   State:\n            D  A\n            B  _\n    *   **Goal Reached:** The tiles are now in the correct anatomical positions (Head D over Chest B, Back A to the right of Head D).\n\n```json\n{\"answer\": \"right up left down right\"}\n```",
          "generated_images": []
        },
        "gpt-5.1": {
          "answer": "right",
          "correct": false,
          "reasoning": "{\"answer\": \"right\"}",
          "generated_images": []
        },
        "emu-3.5": {
          "answer": "up right down left up",
          "correct": false,
          "reasoning": "To solve the puzzle, I need to follow a sequence of moves that will position the blank tile correctly next to each missing piece. The first step is to move the blank tile to the top left corner to start the process. Once there, I can align the missing piece by moving it to the left and adjusting the blank tile accordingly. Next, I'll need to move the blank tile down to position the piece properly below. Finally, I'll adjust the blank tile to the right to complete the alignment. The sequence of moves required is \"up right down left up\". This order ensures that each piece is placed accurately without disrupting the already aligned pieces. Therefore, the final answer is:\n{\n  \"answer\": \"up right down left up\"\n}",
          "generated_images": []
        }
      }
    }
  ]
};
