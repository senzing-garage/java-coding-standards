public class Demo
{
    void run()
    {
        BadOptionParametersException ex = new BadOptionParametersException(
            COMMAND_LINE, CONFIG, "--config", List.of());
    }
}
