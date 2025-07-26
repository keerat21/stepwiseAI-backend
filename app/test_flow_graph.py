from .flow import build_flow
import os

def generate_flow_graph():
    # Build the flow graph
    graph = build_flow()
    
    # Get the graph visualization
    graph_image = graph.get_graph().draw_mermaid_png()
    
    # Save the image
    output_path = os.path.join(os.path.dirname(__file__), "flow_graph.png")
    with open(output_path, "wb") as f:
        f.write(graph_image)
    print(f"Flow graph saved as: {output_path}")

if __name__ == "__main__":
    generate_flow_graph() 